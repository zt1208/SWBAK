# -*- coding: utf-8 -*-
"""
backup_engine.py
备份引擎 - 负责 SSH/Telnet 登录华为/华三/锐捷交换机, 抓取配置并保存
支持多线程并行备份, 按实际主机名分区保存
"""
import os
import re
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from netmiko import ConnectHandler, NetmikoTimeoutException, NetmikoAuthenticationException

from device import Device, VENDOR_TYPES, DEVICE_TYPE_TO_VENDOR


def _safe_dirname(name: str) -> str:
    """把主机名转换为合法的文件夹名"""
    if not name:
        return "unknown"
    name = name.strip()
    # 去掉 Windows 非法字符
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    return name or "unknown"


def parse_hostname(raw_config: str, vendor: str) -> str:
    """从配置文本中解析实际主机名
    华为/华三: sysname XXX
    锐捷: hostname XXX
    """
    if not raw_config:
        return ""
    patterns = {
        "huawei": r"sysname\s+(\S+)",
        "h3c": r"sysname\s+(\S+)",
        "ruijie": r"hostname\s+(\S+)",
    }
    pat = patterns.get(vendor.lower(), r"sysname\s+(\S+)")
    m = re.search(pat, raw_config)
    if m:
        return m.group(1)
    return ""


class BackupEngine:
    """备份引擎

    backup_dir: 配置文件保存根目录
    max_workers: 并发线程数
    """

    def __init__(self, backup_dir: str, max_workers: int = 10,
                 on_progress=None, on_log=None):
        self.backup_dir = backup_dir
        self.max_workers = max(1, int(max_workers))
        self.on_progress = on_progress    # callback(device, status, msg)
        self.on_log = on_log              # callback(msg)
        self._stop = threading.Event()

    # ---------- 用提示符快速判断厂商 (不发命令, 最快) ----------
    def _detect_by_prompt(self, conn, host_tag: str = "") -> str:
        """用 find_prompt() 获取提示符, 根据格式快速判断厂商

        华为: <hostname>     (用户视图)
        华三: <hostname>     (用户视图, 和华为一样, 无法区分)
        锐捷: hostname> 或 hostname#  (无尖括号/方括号包裹)

        返回 huawei/h3c/ruijie 或 None(华为/华三无法区分时)
        """
        try:
            prompt = conn.find_prompt(delay_factor=0.5)
        except Exception:
            return None
        p = prompt.strip()
        if host_tag:
            self._log(f"{host_tag} 提示符: {p}")
        # 锐捷: hostname> 或 hostname# (没有 <> 或 [] 包裹)
        if not p.startswith("<") and not p.startswith("["):
            if p.endswith(">") or p.endswith("#"):
                return "ruijie"
        # 华为/华三: <hostname> 或 [hostname] — 提示符格式相同, 无法区分
        return None

    # ---------- 用已建立的连接发 version, 根据输出关键字判断厂商 ----------
    def _detect_by_version_output(self, conn, host_tag: str = "") -> str:
        """登录成功后, 发 display/show version, 根据输出关键字判断厂商

        使用 send_command_timing (不依赖提示符匹配, 适配 autodetect 连接)
        返回 huawei/h3c/ruijie 或 None
        host_tag: 用于日志前缀, 如 "[10.0.0.1]"
        """
        out = ""
        for cmd in ("display version", "show version"):
            try:
                # send_command_timing 不依赖提示符, 用 delay_factor 控制等待
                out = conn.send_command_timing(cmd, delay_factor=2)
                if out and len(out.strip()) > 5:
                    break
            except Exception:
                out = ""
        if not out:
            return None
        # version 摘要输出到日志 (前 600 字符约 15~20 行, 足够看识别信息又不撑爆日志)
        snippet = out.strip()
        if len(snippet) > 600:
            snippet = snippet[:600] + "\n...(截断, 完整输出见备份文件)"
        if host_tag:
            for line in snippet.splitlines()[:18]:
                self._log(f"{host_tag} version> {line}")
        low = out.lower()
        # 华为: VRP 平台
        if "huawei" in low or "vrp" in low or "virtual router platform" in low:
            return "huawei"
        # 华三: Comware 平台
        if "h3c" in low or "comware" in low or "hpe" in low or "flexnetwork" in low:
            return "h3c"
        # 锐捷: RGOS 平台
        if "ruijie" in low or "rgos" in low or "reynos" in low:
            return "ruijie"
        # 提示符特征: <hostname> 华为, [hostname] 华三, hostname> 锐捷
        if "<" in out and ">" in out:
            return "huawei"
        if "[" in out and "]" in out:
            return "h3c"
        return None

    # ---------- 逐厂商尝试登录 + 提示符/version 确认 (SSH/Telnet 通用) ----------
    def _try_vendors_one_by_one(self, base_params: dict, device: Device, proto: str):
        """逐个厂商尝试登录, 登录后先提示符快速判断, 再 version 确认

        优化点:
        1. 连接超时15秒(兼顾速度与可靠性)
        2. 先用 find_prompt() 快速判断(0.5秒), 不发额外命令
        3. 提示符判断不出再发 version 命令
        4. 确认后直接复用连接, 不重连 (省1-3秒SSH握手)
        """
        # 15秒足够完成SSH握手; 太短会导致 'No existing session' 错误
        fast_params = dict(base_params)
        orig_timeout = int(base_params.get("timeout", 30))
        fast_params["timeout"] = min(orig_timeout, 15)
        fast_params["conn_timeout"] = min(orig_timeout, 15)

        for try_vendor in ("huawei", "h3c", "ruijie"):
            vinfo = VENDOR_TYPES[try_vendor]
            tp = dict(fast_params)
            tp["device_type"] = vinfo[proto]
            try:
                self._log(f"[{device.host}] 尝试 {try_vendor} {proto} 登录...")
                conn = ConnectHandler(**tp)
                # 1. 先用提示符快速判断 (最快, 不发命令)
                confirmed = self._detect_by_prompt(conn, host_tag=f"[{device.host}]")
                if not confirmed:
                    # 2. 提示符无法判断(华为/华三), 用 version 命令确认
                    confirmed = self._detect_by_version_output(conn, host_tag=f"[{device.host}]")
                if confirmed:
                    self._log(f"[{device.host}] 登录成功, 识别为: {confirmed}")
                    # 直接复用当前连接, 不重连!
                    # 华为/华三提示符格式相同, send_command 可正常工作
                    # 锐捷提示符不同, backup_one 会用 send_command_timing 兜底
                    if confirmed != try_vendor:
                        self._log(f"[{device.host}] 复用连接 (原{try_vendor}→{confirmed})")
                    return confirmed, conn
                # 连上了但无法识别, 回退用当前连接
                self._log(f"[{device.host}] 登录成功, 未识别厂商, 回退用: {try_vendor}")
                return try_vendor, conn
            except Exception:
                continue
        return None, None

    # ---------- 登录并识别厂商 ----------
    def _connect_and_detect(self, base_params: dict, device: Device):
        """登录设备并识别厂商, 返回 (vendor, conn)

        优化后流程 (不使用 SSHDetect, 避免其多命令探测开销):
        - 已知厂商: 直接登录, 返回连接
        - auto: 用 autodetect 连接一次 -> 提示符快速判断 -> version 确认 -> 复用连接
                失败则回退到逐厂商尝试
        """
        from device import normalize_vendor
        vendor = normalize_vendor(device.vendor)
        proto = device.protocol.lower()

        # 已知厂商 - 直接登录
        if vendor != "auto":
            vinfo = VENDOR_TYPES[vendor]
            params = dict(base_params)
            params["device_type"] = vinfo["telnet" if proto == "telnet" else "ssh"]
            self._log(f"[{device.host}] 正在 {device.protocol.upper()} 连接 ({vendor})")
            conn = ConnectHandler(**params)
            self._log(f"[{device.host}] 登录成功")
            return vendor, conn

        # auto - 用 autodetect 单次连接, 自行快速识别 (不用 SSHDetect)
        self._log(f"[{device.host}] 自动识别: 正在登录 ({device.protocol})...")
        try:
            detect_params = dict(base_params)
            detect_params["device_type"] = "autodetect"
            # autodetect 需要足够时间完成 SSH 握手, 用设备原始超时
            conn = ConnectHandler(**detect_params)
            self._log(f"[{device.host}] 登录成功, 正在识别厂商...")

            # 1. 提示符快速判断 (0.5秒, 不发命令)
            confirmed = self._detect_by_prompt(conn, host_tag=f"[{device.host}]")

            # 2. 提示符判断不出, 用 send_command_timing 发 version
            if not confirmed:
                confirmed = self._detect_by_version_output(conn, host_tag=f"[{device.host}]")

            if confirmed:
                self._log(f"[{device.host}] 识别为: {confirmed} (复用连接)")
                return confirmed, conn

            # autodetect 连接无法识别 -> 断开, 回退逐厂商
            try:
                conn.disconnect()
            except Exception:
                pass
            self._log(f"[{device.host}] autodetect 未识别, 回退逐厂商尝试")
        except Exception as e:
            self._log(f"[{device.host}] autodetect 连接异常: {e}, 回退逐厂商尝试")

        # 逐厂商尝试登录 + 提示符/version 确认 (回退路径)
        vendor, conn = self._try_vendors_one_by_one(base_params, device, proto)
        if vendor and conn:
            return vendor, conn

        raise ValueError("登录失败或无法识别厂商类型(三种厂商均无法连接/识别)")

    def backup_one(self, device: Device) -> Device:
        if self._stop.is_set():
            device.status = "失败"
            device.message = "已取消"
            return device

        device.status = "备份中"
        device.message = "正在连接..."
        self._emit_progress(device)

        conn = None
        try:
            base_params = {
                "host": device.host,
                "port": int(device.port),
                "username": device.username,
                "password": device.password,
                "timeout": int(device.timeout),
                "conn_timeout": int(device.timeout),
                "global_delay_factor": 1,
            }
            if device.enable_password:
                base_params["secret"] = device.enable_password

            # 先登录设备, 登录成功后再识别厂商, 复用同一条连接抓配置
            vendor, conn = self._connect_and_detect(base_params, device)
            device.vendor = vendor  # 回写识别结果
            vinfo = VENDOR_TYPES[vendor]

            # 进入特权模式(若提供了 enable 密码)
            if device.enable_password:
                try:
                    conn.enable()
                except Exception:
                    pass

            # 关闭分页 - 不同厂商命令不同, 失败不影响主流程
            try:
                conn.send_command_timing(vinfo["paging_cmd"])
            except Exception:
                pass

            # 抓取配置
            show_cmd = vinfo["show_cmd"]
            self._log(f"[{device.host}] 执行: {show_cmd}")
            config_text = ""
            is_autodetect = getattr(conn, 'device_type', '') == 'autodetect'

            if is_autodetect:
                # autodetect 连接: send_command 可能无法匹配提示符导致超时
                # 直接用 send_command_timing (不依赖提示符), delay_factor=3 确保读完
                try:
                    config_text = conn.send_command_timing(show_cmd, delay_factor=3)
                except Exception:
                    pass
            else:
                # 已知 device_type: send_command 能匹配提示符, 获取完整输出
                try:
                    config_text = conn.send_command(show_cmd, read_timeout=30,
                                                    delay_factor=1, max_loops=500)
                except Exception:
                    pass
                if not config_text or len(config_text.strip()) < 20:
                    # 兜底: send_command_timing
                    try:
                        config_text = conn.send_command_timing(show_cmd, delay_factor=2)
                    except Exception:
                        config_text = ""

            # 配置摘要输出到日志 (前 10 行, 让用户能看到交换机实际输出的开头内容)
            cfg_lines = [l.rstrip() for l in (config_text or "").splitlines()
                         if l.strip()]
            cfg_line_count = len(cfg_lines)
            cfg_char_count = len(config_text or "")
            self._log(f"[{device.host}] 配置输出: {cfg_line_count} 行 / {cfg_char_count} 字符")
            if cfg_lines:
                for line in cfg_lines[:10]:
                    self._log(f"[{device.host}] cfg> {line}")
                if cfg_line_count > 10:
                    self._log(f"[{device.host}] cfg> ... 省略 {cfg_line_count - 10} 行 (完整内容见备份文件)")

            # 解析实际主机名
            hostname = parse_hostname(config_text, vendor)
            if not hostname:
                # 用 name_cmd 再试一次
                try:
                    if is_autodetect:
                        name_out = conn.send_command_timing(vinfo["name_cmd"],
                                                             delay_factor=2)
                    else:
                        name_out = conn.send_command(vinfo["name_cmd"],
                                                     read_timeout=8, delay_factor=1)
                    hostname = parse_hostname(name_out, vendor)
                except Exception:
                    pass
            device.real_hostname = hostname or device.name or device.host

            # 按 分组/设备实际主机名 分层保存
            # 同一分组的设备放在同一个文件夹下, 便于查找
            group_name = _safe_dirname(device.group) if device.group else "默认"
            folder = os.path.join(self.backup_dir, group_name,
                                  _safe_dirname(device.real_hostname))
            os.makedirs(folder, exist_ok=True)

            # ---------- 与上次 latest 对比，无变化则不更新 ----------
            latest = os.path.join(folder, "latest.txt")
            has_latest = os.path.exists(latest)
            same_as_latest = False
            if has_latest:
                with open(latest, "r", encoding="utf-8", errors="ignore") as f:
                    old_text = f.read()
                    # 按行规范化（去掉尾部空白和空行差异），逐行比较
                    def norm_lines(s):
                        return [l.rstrip() for l in s.splitlines()]
                    if norm_lines(old_text) == norm_lines(config_text):
                        same_as_latest = True

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{_safe_dirname(device.real_hostname)}_{ts}.txt"
            filepath = os.path.join(folder, filename)

            if same_as_latest:
                # 配置无变化: 不新建文件，不覆盖 latest，状态标"无变化"
                # 复用上次的 last_file (最后变化版本)
                device.status = "无变化"
                device.message = "配置无变化，未更新"
                device.last_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                # 保留上次文件路径不变，不新建不覆盖
                self._log(f"[{device.host}] 配置无变化，跳过保存")
            else:
                # 配置有变化: 先保存新文件, 暂不更新 latest.txt
                # latest.txt 等 _on_progress 生成 diff 后再更新

                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(config_text)

                device.status = "成功"
                device.message = f"配置变化，已保存 {filename}"
                device.last_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                device.last_file = filepath
                size_kb = cfg_char_count / 1024
                self._log(f"[{device.host}] 配置变化，备份成功 -> {filepath} ({size_kb:.1f} KB)")

                # 保存旧 latest 内容到设备对象, 供 _write_diff_file 使用
                device._old_latest = old_text if has_latest else None

        except NetmikoAuthenticationException as e:
            device.status = "失败"
            device.message = f"认证失败: {e}"
            self._log(f"[{device.host}] 认证失败")
        except NetmikoTimeoutException as e:
            device.status = "失败"
            device.message = f"连接超时: {e}"
            self._log(f"[{device.host}] 连接超时")
        except Exception as e:
            device.status = "失败"
            device.message = f"异常: {e}"
            self._log(f"[{device.host}] 异常: {traceback.format_exc(limit=2)}")
        finally:
            if conn is not None:
                try:
                    conn.disconnect()
                except Exception:
                    pass
            self._emit_progress(device)
        return device

    # ---------- 批量多线程备份 ----------
    def backup_batch(self, devices: list) -> list:
        self._stop.clear()
        total = len(devices)
        self._log(f"开始批量备份, 共 {total} 台, 并发 {self.max_workers}")
        results = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            future_map = {ex.submit(self.backup_one, d): d for d in devices}
            done = 0
            for fut in as_completed(future_map):
                if self._stop.is_set():
                    break
                try:
                    res = fut.result()
                except Exception as e:
                    res = future_map[fut]
                    res.status = "失败"
                    res.message = f"线程异常: {e}"
                results.append(res)
                done += 1
                if self.on_log:
                    self.on_log(f"进度: {done}/{total}")
        self._log("批量备份结束")
        return results

    def stop(self):
        self._stop.set()
        self._log("已请求停止备份(当前任务完成后退出)")

    # ---------- 内部回调 ----------
    def _emit_progress(self, device: Device):
        if self.on_progress:
            try:
                self.on_progress(device)
            except Exception:
                pass

    def _log(self, msg: str):
        if self.on_log:
            try:
                self.on_log(msg)
            except Exception:
                pass
