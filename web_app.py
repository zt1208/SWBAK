# -*- coding: utf-8 -*-
"""
web_app.py
SWBAK Web 版主程序 (B/S 架构)

启动: python web_app.py
访问: http://localhost:5000

架构:
  - Flask 提供 REST API + SSE 实时推送
  - 复用 backup_engine / importer / notifier / scheduler / config_compare 业务模块
  - SQLite 持久化 (db.py)
  - 单页前端 (templates/index.html + static/)
"""
import hashlib
import io
import os
import queue
import threading
import time
import traceback
from datetime import datetime, timedelta

from flask import (Flask, render_template, request, jsonify, Response,
                   send_file, stream_with_context, session, redirect, url_for)

import db
from device import Device, VENDOR_LABELS, normalize_vendor
from backup_engine import BackupEngine, parse_hostname
from importer import import_devices, export_template
from notifier import send_report, build_report_html
from scheduler import BackupScheduler
import config_compare

APP_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["JSON_AS_ASCII"] = False

# ---------- 登录认证 ----------
AUTH_USER = "cdu"
# 登录密码的 sha256 哈希 (明文不入库; 修改密码: hashlib.sha256("新密码".encode()).hexdigest())
AUTH_PASS_HASH = "6409e868aa158d808b9ec64e63512a43946cdeeaa8260b02ca864a7d6a10c87d"
# 会话有效期 7 天
SESSION_LIFETIME = timedelta(days=7)
# 防爆破: 失败 5 次锁 5 分钟
LOGIN_MAX_FAILS = 5
LOGIN_LOCK_SECONDS = 300

# secret_key 持久化到 DB, 服务重启不掉线
# (先确保表存在 - 全新部署时 init() 还未执行)
db.init_db()
_secret = db.get_setting("secret_key", "")
if not _secret:
    _secret = os.urandom(32).hex()
    db.set_setting("secret_key", _secret)
app.secret_key = _secret
app.config["PERMANENT_SESSION_LIFETIME"] = SESSION_LIFETIME

# 内存级防爆破记录 {ip: [fail_count, lock_until_ts]}
_login_guard = {}
_login_guard_lock = threading.Lock()


def _client_ip() -> str:
    return request.headers.get("X-Forwarded-For", request.remote_addr or "?").split(",")[0].strip()


def _check_login_locked(ip: str):
    """返回 (是否锁定, 剩余秒数)"""
    with _login_guard_lock:
        rec = _login_guard.get(ip)
        if rec and rec[1] > time.time():
            return True, int(rec[1] - time.time())
        # 锁过期或不存在
        if rec and rec[1] and rec[1] <= time.time():
            _login_guard.pop(ip, None)
    return False, 0


def _record_login_fail(ip: str):
    with _login_guard_lock:
        rec = _login_guard.get(ip, [0, 0])
        rec[0] += 1
        if rec[0] >= LOGIN_MAX_FAILS:
            rec[1] = time.time() + LOGIN_LOCK_SECONDS
            rec[0] = 0
        _login_guard[ip] = rec


def _hash_pwd(pwd: str) -> str:
    return hashlib.sha256(pwd.encode("utf-8")).hexdigest()


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        ip = _client_ip()
        locked, wait = _check_login_locked(ip)
        if locked:
            return render_template("login.html", error=f"尝试次数过多, 请 {wait} 秒后再试"), 429
        user = (request.form.get("username") or "").strip()
        pwd = request.form.get("password") or ""
        if user == AUTH_USER and _hash_pwd(pwd) == AUTH_PASS_HASH:
            session["user"] = user
            session.permanent = True
            with _login_guard_lock:
                _login_guard.pop(ip, None)
            return redirect(url_for("index"))
        _record_login_fail(ip)
        return render_template("login.html", error="账号或密码错误"), 401
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.before_request
def require_login():
    # 放行: 登录页 / 静态资源; 其余一律要求已登录
    endpoint = request.endpoint or ""
    if endpoint in ("login", "static"):
        return None
    if session.get("user"):
        return None
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "msg": "未登录或会话已过期, 请重新登录", "need_login": True}), 401
    return redirect(url_for("login"))

# 默认设置 (首次启动写入 DB)
# 注意: backup_dir 用相对路径 "backups", 通用化部署不绑定绝对路径
DEFAULT_SETTINGS = {
    "backup_dir": "backups",
    "max_workers": 10,
    "default_timeout": 30,
    "mail_enabled": False,
    "smtp_host": "",
    "smtp_port": 465,
    "smtp_ssl": True,
    "mail_sender": "",
    "mail_password": "",
    "mail_recipients": "",
    "schedule_enabled": False,
    "schedule_mode": "interval",      # interval / daily
    "schedule_interval_hours": 24,
    "schedule_daily_hour": 2,
    "last_username": "",
    "last_password": "",
    "last_enable_password": "",
    "last_vendor": "auto",
    "last_protocol": "ssh",
    "last_port": 22,
    "last_group": "默认",
}


def get_settings() -> dict:
    """读取设置, 合并默认值"""
    stored = db.get_all_settings()
    merged = dict(DEFAULT_SETTINGS)
    merged.update(stored)
    # 确保 backup_dir 为绝对路径 (运行时文件系统访问用)
    bd = merged.get("backup_dir") or DEFAULT_SETTINGS["backup_dir"]
    if not os.path.isabs(bd):
        bd = os.path.join(APP_DIR, bd)
    merged["backup_dir"] = os.path.normpath(bd)
    return merged


# ---------- 路径通用化: DB 与 API 一律存/传 "相对于 backup_dir" 的相对路径 ----------
# 这样整个项目目录(含 DB)移动到任意位置, 路径仍有效
def to_rel_path(abs_path: str, backup_dir: str) -> str:
    """绝对路径 -> 相对 backup_dir 的相对路径; 转换失败返回原值"""
    if not abs_path:
        return ""
    try:
        return os.path.relpath(abs_path, backup_dir)
    except ValueError:
        return abs_path


def resolve_backup_path(rel_path: str, backup_dir: str):
    """相对路径 -> 绝对路径, 并做安全校验(必须在 backup_dir 之下)
    返回 (abs_path, error_msg); 校验通过 error_msg 为 None
    """
    if not rel_path:
        return None, "路径为空"
    # 拼接并规范化, 抵御 ../ 越权
    abs_path = os.path.normpath(os.path.join(backup_dir, rel_path))
    bd_norm = os.path.normpath(backup_dir)
    # 必须位于 backup_dir 之内 (兼容 Windows 盘符)
    if not (abs_path == bd_norm or abs_path.startswith(bd_norm + os.sep)):
        return None, "非法路径"
    return abs_path, None


# ====================== 备份任务管理器 ======================
class BackupManager:
    """全局备份任务管理: 后台执行 + SSE 事件广播"""

    def __init__(self):
        self.engine: BackupEngine = None
        self.thread = None
        self.is_running = False
        self._lock = threading.Lock()
        self._clients = []           # SSE 客户端 queue 列表
        self.total = 0
        self.done = 0
        self.ok = 0
        self.fail = 0
        self.start_time = None
        self._stop_flag = False

    def start(self, devices: list) -> bool:
        """启动一次备份, 已在运行则返回 False"""
        with self._lock:
            if self.is_running:
                return False
            self.is_running = True
            self._stop_flag = False
            self.total = len(devices)
            self.done = 0
            self.ok = 0
            self.fail = 0
            self.start_time = datetime.now()

        settings = get_settings()
        self.engine = BackupEngine(
            backup_dir=settings["backup_dir"],
            max_workers=settings["max_workers"],
            on_progress=self._on_progress,
            on_log=self._on_log,
        )
        self.thread = threading.Thread(target=self._run,
                                       args=(devices, settings), daemon=True)
        self.thread.start()
        return True

    def _run(self, devices: list, settings: dict):
        try:
            self._broadcast({"type": "start", "total": self.total,
                             "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
            results = self.engine.backup_batch(devices)
            # 备份后处理: 报告 + 邮件
            self._post_backup(results, settings)
        except Exception as e:
            self._log(f"备份任务异常: {traceback.format_exc(limit=3)}")
        finally:
            with self._lock:
                self.is_running = False
            self._broadcast({"type": "done", "total": self.total,
                             "done": self.done, "ok": self.ok, "fail": self.fail})

    def _on_progress(self, device: Device):
        """单台设备状态变更"""
        # 复用引擎的 backup_dir (已在 start 时从 settings 注入), 避免每台设备重复读 DB
        backup_dir = self.engine.backup_dir if self.engine else get_settings()["backup_dir"]
        # 存 DB 时把绝对路径转成相对 backup_dir 的相对路径 (通用化部署)
        rel_last_file = to_rel_path(device.last_file, backup_dir) if device.last_file else ""

        # 写回 DB
        try:
            did = getattr(device, "id", None)
            if did:
                db.update_device_status(
                    did, device.status, device.message,
                    device.last_time, rel_last_file,
                    device.real_hostname, device.vendor,
                )
        except Exception:
            pass

        if device.status == "成功":
            # 配置变化: 记录备份历史 + 生成 diff 标注文件
            try:
                size = 0
                if device.last_file and os.path.exists(device.last_file):
                    size = os.path.getsize(device.last_file)
                db.add_backup(
                    device_host=device.host,
                    hostname=device.real_hostname or device.name or device.host,
                    group=device.group,
                    filepath=rel_last_file,
                    filename=os.path.basename(device.last_file) if device.last_file else "",
                    backup_time=device.last_time,
                    size_chars=size,
                    vendor=device.vendor,
                    status="成功",
                    message=device.message,
                )
                # 生成 diff 标注文件: 与上次 latest 对比
                self._write_diff_file(device, backup_dir)
                with self._lock:
                    self.ok += 1
            except Exception:
                pass
        elif device.status == "失败":
            with self._lock:
                self.fail += 1
        elif device.status == "无变化":
            # 配置无变化: 不记录备份历史, 不更新文件, 只更新设备状态
            # 已通过 DB update 刷新了 last_time, 因此仍可看到"最近备份时间"
            with self._lock:
                self.ok += 1  # 无变化本质上也是成功, 计入 ok 总数
            self._log(f"[{device.host}] 配置无变化，跳过历史记录")

        # 进度计数 (成功/失败/无变化 才算完成)
        if device.status in ("成功", "失败", "无变化"):
            with self._lock:
                self.done += 1

        self._broadcast({
            "type": "progress",
            "device": {
                "id": getattr(device, "id", None),
                "host": device.host,
                "name": device.real_hostname or device.name or device.host,
                "vendor": device.vendor,
                "status": device.status,
                "message": device.message,
                "last_time": device.last_time,
                "real_hostname": device.real_hostname,
            },
            "done": self.done,
            "total": self.total,
            "ok": self.ok,
            "fail": self.fail,
        })

    def _write_diff_file(self, device: Device, backup_dir: str):
        """配置变化时生成 .diff 标注文件, 与备份文件同目录
        比较: 旧(latest.txt 备份前的内容) vs 新(刚保存的文件)
        """
        if not device.last_file or not os.path.exists(device.last_file):
            return
        folder = os.path.dirname(device.last_file)
        latest = os.path.join(folder, "latest.txt")
        # 用引擎中保存的旧内容 (备份前读取的), 避免 latest.txt 已更新的问题
        old_content = getattr(device, "_old_latest", None)
        if old_content is None:
            # 首次备份, 无旧版本, 跳过 diff 但更新 latest
            pass
        else:
            # 生成 diff
            import difflib
            new_content = ""
            with open(device.last_file, "r", encoding="utf-8", errors="ignore") as f:
                new_content = f.read()
            old_lines = old_content.splitlines(keepends=True)
            new_lines = new_content.splitlines(keepends=True)
            diff_lines = list(difflib.unified_diff(
                old_lines, new_lines,
                fromfile=f"旧版本 ({os.path.basename(latest)})",
                tofile=f"新版本 ({os.path.basename(device.last_file)})",
                lineterm="",
            ))
            if diff_lines:
                diff_path = os.path.splitext(device.last_file)[0] + ".diff"
                with open(diff_path, "w", encoding="utf-8") as f:
                    f.write("\n".join(diff_lines))
                self._log(f"[{device.host}] diff 已标注 -> {diff_path}")
        # 更新 latest.txt (新配置作为当前最新)
        if os.path.exists(device.last_file):
            import shutil
            shutil.copy2(device.last_file, latest)
            self._log(f"[{device.host}] latest.txt 已更新")

    def _on_log(self, msg: str):
        self._log(msg)

    def _log(self, msg: str):
        self._broadcast({"type": "log", "msg": f"[{datetime.now():%H:%M:%S}] {msg}"})

    def stop(self):
        if self.engine:
            self.engine.stop()
            self._log("用户请求停止备份")

    def _post_backup(self, results: list, settings: dict):
        """备份完成后: 自动导出 Excel 报告 + 邮件通知"""
        # 1. Excel 报告
        try:
            report_path = self._export_report(results, settings)
            if report_path:
                self._log(f"已生成报告: {report_path}")
        except Exception as e:
            self._log(f"报告导出失败: {e}")

        # 2. 邮件通知
        if settings.get("mail_enabled"):
            try:
                html = build_report_html("交换机配置备份报告", results)
                recipients = [r.strip() for r in
                              str(settings.get("mail_recipients", "")).replace(";", ",").split(",")
                              if r.strip()]
                ok, msg = send_report(
                    smtp_host=settings["smtp_host"],
                    smtp_port=int(settings["smtp_port"]),
                    sender=settings["mail_sender"],
                    password=settings["mail_password"],
                    recipients=recipients,
                    subject=f"交换机配置备份报告 {datetime.now():%Y-%m-%d %H:%M}",
                    html_body=html,
                    use_ssl=settings.get("smtp_ssl", True),
                )
                self._log(f"邮件通知: {msg}")
            except Exception as e:
                self._log(f"邮件发送失败: {e}")

    @staticmethod
    def _export_report(results: list, settings: dict) -> str:
        import xlsxwriter
        reports_dir = os.path.join(APP_DIR, "reports")
        os.makedirs(reports_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(reports_dir, f"backup_report_{ts}.xlsx")
        wb = xlsxwriter.Workbook(path)
        ws_ok = wb.add_worksheet("变化")
        ws_unchanged = wb.add_worksheet("无变化")
        ws_fail = wb.add_worksheet("失败")
        headers = ["设备名", "IP", "厂商", "状态", "详情", "备份时间", "文件"]
        bold = wb.add_format({"bold": True, "bg_color": "#f0f3f7", "border": 1})
        cell = wb.add_format({"border": 1, "valign": "top"})
        for ws in (ws_ok, ws_unchanged, ws_fail):
            for c, h in enumerate(headers):
                ws.write(0, c, h, bold)
                ws.set_column(c, c, 18)
        r_ok = r_fail = r_unchanged = 1
        for d in results:
            row = [d.real_hostname or d.name or d.host, d.host, d.vendor,
                   d.status, d.message, d.last_time, d.last_file or ""]
            if d.status == "成功":
                for c, v in enumerate(row):
                    ws_ok.write(r_ok, c, v, cell)
                r_ok += 1
            elif d.status == "无变化":
                for c, v in enumerate(row):
                    ws_unchanged.write(r_unchanged, c, v, cell)
                r_unchanged += 1
            else:
                for c, v in enumerate(row):
                    ws_fail.write(r_fail, c, v, cell)
                r_fail += 1
        wb.close()
        return path

    # ---------- SSE 客户端管理 ----------
    def register(self) -> queue.Queue:
        q = queue.Queue()
        with self._lock:
            self._clients.append(q)
        # 推送当前状态快照
        q.put({"type": "snapshot",
               "is_running": self.is_running,
               "total": self.total, "done": self.done,
               "ok": self.ok, "fail": self.fail})
        return q

    def unregister(self, q: queue.Queue):
        with self._lock:
            if q in self._clients:
                self._clients.remove(q)

    def _broadcast(self, event: dict):
        with self._lock:
            clients = list(self._clients)
        dead = []
        for q in clients:
            try:
                q.put_nowait(event)
            except queue.Full:
                dead.append(q)
        if dead:
            with self._lock:
                for q in dead:
                    if q in self._clients:
                        self._clients.remove(q)


backup_mgr = BackupManager()

# ====================== 定时备份调度器 ======================
scheduler: BackupScheduler = None


def scheduled_backup_task():
    """定时任务触发: 全量备份"""
    if backup_mgr.is_running:
        backup_mgr._log("定时任务触发, 但已有备份在运行, 跳过")
        return
    devices = db.list_devices()
    if not devices:
        backup_mgr._log("定时任务触发, 但无设备, 跳过")
        return
    backup_mgr._log("定时备份任务触发")
    backup_mgr.start(devices)


def apply_scheduler():
    """根据设置启动/重启定时调度器"""
    global scheduler
    s = get_settings()
    if scheduler:
        scheduler.stop()
        scheduler = None
    if s.get("schedule_enabled"):
        scheduler = BackupScheduler(
            task_fn=scheduled_backup_task,
            mode=s.get("schedule_mode", "interval"),
            interval_hours=int(s.get("schedule_interval_hours", 24)),
            daily_hour=int(s.get("schedule_daily_hour", 2)),
            on_log=lambda m: backup_mgr._log(m),
        )
        scheduler.start()


# ====================== 路由: 页面 ======================
@app.route("/")
def index():
    return render_template("index.html")


# ====================== 路由: 元信息 ======================
@app.route("/api/meta")
def api_meta():
    return jsonify({
        "vendor_labels": VENDOR_LABELS,
        "vendors": ["auto", "huawei", "h3c", "ruijie"],
    })


# ====================== 路由: 设备管理 ======================
@app.route("/api/devices")
def api_list_devices():
    devices = db.list_devices()
    return jsonify([_device_dict(d) for d in devices])


@app.route("/api/devices", methods=["POST"])
def api_add_device():
    data = request.get_json(force=True)
    try:
        d = _device_from_json(data)
        db.add_device(d)
        # 记住凭据, 下次自动填充
        _save_last_credentials(data)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 400


@app.route("/api/devices/<int:did>", methods=["PUT"])
def api_edit_device(did):
    data = request.get_json(force=True)
    try:
        d = _device_from_json(data)
        db.update_device(did, d)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 400


@app.route("/api/devices/<int:did>", methods=["DELETE"])
def api_delete_device(did):
    db.delete_device(did)
    return jsonify({"ok": True})


@app.route("/api/devices/clear", methods=["POST"])
def api_clear_devices():
    db.clear_devices()
    return jsonify({"ok": True})


@app.route("/api/devices/import", methods=["POST"])
def api_import_file():
    """上传 Excel/CSV/TXT 文件导入设备
    支持附带默认凭据: 文件中缺的字段用表单默认值补充
    """
    f = request.files.get("file")
    if not f:
        return jsonify({"ok": False, "msg": "未上传文件"}), 400
    # 读取默认凭据 (表中缺字段时补充)
    defaults = {
        "username": request.form.get("username", ""),
        "password": request.form.get("password", ""),
        "enable_password": request.form.get("enable_password", ""),
        "vendor": normalize_vendor(request.form.get("vendor", "auto")),
        "protocol": request.form.get("protocol", "ssh") or "ssh",
        "group": request.form.get("group", "默认") or "默认",
        "port": request.form.get("port", ""),
    }
    # 记住凭据
    _save_last_credentials(defaults)

    # 保存到临时文件
    tmp = os.path.join(APP_DIR, "_tmp_import" + os.path.splitext(f.filename)[1])
    f.save(tmp)
    try:
        devices = import_devices(tmp)
        # 合并默认凭据: 文件中缺的字段用默认值填充
        for d in devices:
            if not d.username and defaults["username"]:
                d.username = defaults["username"]
            if not d.password and defaults["password"]:
                d.password = defaults["password"]
            if not d.enable_password and defaults["enable_password"]:
                d.enable_password = defaults["enable_password"]
            if not d.group or d.group == "默认":
                d.group = defaults["group"]
            if not d.vendor or d.vendor == "auto":
                d.vendor = defaults["vendor"]
            if defaults["port"]:
                try:
                    d.port = int(defaults["port"])
                except ValueError:
                    pass
        result = db.merge_devices(devices)
        return jsonify({"ok": True, **result})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 400
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


@app.route("/api/devices/batch", methods=["POST"])
def api_batch_entry():
    """粘贴文本批量录入
    支持:
      - 简化格式: 每行 IP [用户名] [密码] [厂商] [协议], 缺省用表单默认值
      - 统一密码: {text: IPs, username, password, vendor, protocol, group}
    """
    data = request.get_json(force=True)
    mode = data.get("mode", "simple")
    if mode == "unified":
        # 统一密码: text 是 IP 列表
        ips = [ln.strip() for ln in str(data.get("text", "")).splitlines() if ln.strip()]
        vendor = normalize_vendor(data.get("vendor", "auto"))
        protocol = data.get("protocol", "ssh") or "ssh"
        port = int(data.get("port", 22 if protocol == "ssh" else 23))
        group = data.get("group", "默认") or "默认"
        username = data.get("username", "")
        password = data.get("password", "")
        enable_password = data.get("enable_password", "")
        devices = [Device(host=ip, username=username, password=password,
                          enable_password=enable_password, vendor=vendor,
                          protocol=protocol, port=port, group=group)
                   for ip in ips]
        # 记住凭据
        _save_last_credentials(data)
    else:
        # 简化格式: 每行 host [user] [pwd] [vendor] [protocol], 缺省用表单默认值
        default_user = data.get("username", "")
        default_pwd = data.get("password", "")
        default_enable = data.get("enable_password", "")
        default_vendor = normalize_vendor(data.get("vendor", "auto"))
        default_protocol = data.get("protocol", "ssh") or "ssh"
        default_group = data.get("group", "默认") or "默认"
        default_port = int(data.get("port", 22 if default_protocol == "ssh" else 23))
        _save_last_credentials(data)

        devices = []
        for ln in str(data.get("text", "")).splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            parts = ln.replace(",", " ").split()
            if len(parts) < 1:
                continue
            host = parts[0]
            # 逐字段: 有的用行内值, 没有的用默认值
            user = parts[1] if len(parts) > 1 and parts[1] else default_user
            pwd = parts[2] if len(parts) > 2 and parts[2] else default_pwd
            # 只有 1 个字段: 纯 IP, 全部用默认值
            if len(parts) == 1:
                user = default_user
                pwd = default_pwd
            if not user:
                continue  # 没有用户名, 跳过
            vendor = normalize_vendor(parts[3]) if len(parts) > 3 and parts[3] else default_vendor
            protocol = parts[4].lower() if len(parts) > 4 and parts[4].lower() in ("ssh", "telnet") else default_protocol
            port = 23 if protocol == "telnet" else default_port
            enable = parts[5] if len(parts) > 5 and parts[5] else default_enable
            devices.append(Device(host=host, username=user, password=pwd,
                                  enable_password=enable, vendor=vendor,
                                  protocol=protocol, port=port, group=default_group))
    result = db.merge_devices(devices)
    return jsonify({"ok": True, **result})


@app.route("/api/devices/template")
def api_template():
    """导出导入模板"""
    fmt = request.args.get("fmt", "xlsx")
    tmp = os.path.join(APP_DIR, f"_template.{fmt}")
    export_template(tmp)
    return send_file(tmp, as_attachment=True,
                     download_name=f"设备导入模板.{fmt}")


# ====================== 路由: 备份 ======================
@app.route("/api/backup", methods=["POST"])
def api_start_backup():
    if backup_mgr.is_running:
        return jsonify({"ok": False, "msg": "已有备份任务在运行"}), 400
    data = request.get_json(silent=True) or {}
    all_devices = db.list_devices()
    if data.get("all"):
        devices = all_devices
    else:
        ids = set(data.get("ids", []))
        devices = [d for d in all_devices if getattr(d, "id", None) in ids]
    if not devices:
        return jsonify({"ok": False, "msg": "没有可备份的设备"}), 400
    backup_mgr.start(devices)
    return jsonify({"ok": True, "total": len(devices)})


@app.route("/api/backup/stop", methods=["POST"])
def api_stop_backup():
    backup_mgr.stop()
    return jsonify({"ok": True})


@app.route("/api/backup/status")
def api_backup_status():
    return jsonify({
        "is_running": backup_mgr.is_running,
        "total": backup_mgr.total,
        "done": backup_mgr.done,
        "ok": backup_mgr.ok,
        "fail": backup_mgr.fail,
    })


@app.route("/api/backup/stream")
def api_backup_stream():
    """SSE 实时推送备份进度与日志"""
    q = backup_mgr.register()

    @stream_with_context
    def gen():
        try:
            while True:
                try:
                    event = q.get(timeout=25)
                except queue.Empty:
                    # 心跳保活
                    yield ": ping\n\n"
                    continue
                import json as _json
                yield f"data: {_json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("type") == "done":
                    # 推完 done 后再保活几秒, 让前端收尾
                    yield ": ping\n\n"
                    break
        finally:
            backup_mgr.unregister(q)

    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no",
                             "Connection": "keep-alive"})


# ====================== 路由: 备份历史与文件查看 ======================
@app.route("/api/backups")
def api_backup_history():
    host = request.args.get("host", "")
    limit = int(request.args.get("limit", 500))
    return jsonify(db.list_backup_history(limit=limit, host=host))


@app.route("/api/backups/tree")
def api_backup_tree():
    """返回备份目录树: 分组/设备/文件
    path 字段统一返回 "相对 backup_dir" 的相对路径, 便于通用化部署
    """
    settings = get_settings()
    bd = settings["backup_dir"]
    tree = []
    if not os.path.isdir(bd):
        return jsonify(tree)
    for group in sorted(os.listdir(bd)):
        gp = os.path.join(bd, group)
        if not os.path.isdir(gp):
            continue
        group_node = {"name": group, "devices": []}
        for dev in sorted(os.listdir(gp)):
            dp = os.path.join(gp, dev)
            if not os.path.isdir(dp):
                continue
            files = []
            for f in sorted(os.listdir(dp), reverse=True):
                fp = os.path.join(dp, f)
                if os.path.isfile(fp) and (f.endswith(".txt") or f.endswith(".cfg") or f.endswith(".diff")):
                    files.append({
                        "name": f,
                        "path": to_rel_path(fp, bd),
                        "time": datetime.fromtimestamp(os.path.getmtime(fp)).strftime("%Y-%m-%d %H:%M:%S"),
                        "size": os.path.getsize(fp),
                        "is_latest": f in ("latest.txt", "latest.cfg"),
                    })
            if files:
                group_node["devices"].append({"name": dev, "files": files})
        if group_node["devices"]:
            tree.append(group_node)
    return jsonify(tree)


@app.route("/api/backups/file")
def api_backup_file():
    """查看配置文件内容 (path 为相对 backup_dir 的相对路径)"""
    rel = request.args.get("path", "")
    settings = get_settings()
    abs_path, err = resolve_backup_path(rel, settings["backup_dir"])
    if err or not os.path.isfile(abs_path):
        return jsonify({"ok": False, "msg": "文件不存在" if not err else err}), 404
    with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    return jsonify({"ok": True, "content": content,
                    "name": os.path.basename(abs_path)})


@app.route("/api/backups/download")
def api_backup_download():
    rel = request.args.get("path", "")
    settings = get_settings()
    abs_path, err = resolve_backup_path(rel, settings["backup_dir"])
    if err or not os.path.isfile(abs_path):
        return jsonify({"ok": False, "msg": "文件不存在" if not err else err}), 404
    return send_file(abs_path, as_attachment=True,
                     download_name=os.path.basename(abs_path))


# ====================== 路由: 配置对比 / 搜索 ======================
@app.route("/api/compare", methods=["POST"])
def api_compare():
    data = request.get_json(force=True)
    old_rel = data.get("old", "")
    new_rel = data.get("new", "")
    if not (old_rel and new_rel):
        return jsonify({"ok": False, "msg": "请选择两个文件"}), 400
    settings = get_settings()
    bd = settings["backup_dir"]
    old_abs, err1 = resolve_backup_path(old_rel, bd)
    new_abs, err2 = resolve_backup_path(new_rel, bd)
    if err1 or err2 or not os.path.isfile(old_abs) or not os.path.isfile(new_abs):
        return jsonify({"ok": False, "msg": "文件不存在或非法路径"}), 400
    result = config_compare.compare(old_abs, new_abs)
    return jsonify({"ok": True, **result})


@app.route("/api/search", methods=["POST"])
def api_search():
    data = request.get_json(force=True)
    keyword = data.get("keyword", "").strip()
    if not keyword:
        return jsonify({"ok": False, "msg": "请输入关键字"}), 400
    settings = get_settings()
    bd = settings["backup_dir"]
    raw = config_compare.search_in_configs(bd, keyword)
    # 搜索结果里的绝对路径转为相对 backup_dir, 通用化
    results = []
    for abs_path, line_no, line_text in raw:
        results.append((to_rel_path(abs_path, bd), line_no, line_text))
    # 截断返回前 500 条, 避免过大
    return jsonify({"ok": True, "results": results[:500],
                    "total": len(results)})


# ====================== 路由: 统计 ======================
@app.route("/api/stats")
def api_stats():
    devices = db.list_devices()
    total = len(devices)
    ok = sum(1 for d in devices if d.status == "成功")
    fail = sum(1 for d in devices if d.status == "失败")
    groups = {}
    for d in devices:
        groups[d.group] = groups.get(d.group, 0) + 1
    return jsonify({
        "total": total, "ok": ok, "fail": fail,
        "groups": groups,
        "scheduler_running": scheduler.is_running() if scheduler else False,
        "scheduler_next": scheduler.next_run_str() if scheduler else "未启用",
        "backup_running": backup_mgr.is_running,
    })


# ====================== 路由: 设置 ======================
@app.route("/api/settings")
def api_get_settings():
    s = get_settings()
    # 设置页展示原始存储的 backup_dir (相对路径), 避免把解析后的绝对路径写回 DB
    raw_stored = db.get_all_settings()
    if "backup_dir" in raw_stored:
        s["backup_dir"] = raw_stored["backup_dir"]
    return jsonify(s)


@app.route("/api/settings", methods=["POST"])
def api_save_settings():
    data = request.get_json(force=True)
    # 密码字段为占位时不更新
    for pwd_key in ("mail_password",):
        if data.get(pwd_key) == "********":
            data.pop(pwd_key)
    db.update_settings(data)
    # 设置变更可能影响调度器
    apply_scheduler()
    return jsonify({"ok": True})


# ====================== 路由: 测试单台备份 ======================
@app.route("/api/test", methods=["POST"])
def api_test_backup():
    """测试单台设备连接 (不保存)"""
    data = request.get_json(force=True)
    d = _device_from_json(data)
    settings = get_settings()
    result_holder = {}

    def on_progress(dev):
        result_holder["status"] = dev.status
        result_holder["message"] = dev.message
        result_holder["real_hostname"] = dev.real_hostname
        result_holder["vendor"] = dev.vendor

    logs = []
    engine = BackupEngine(
        backup_dir=settings["backup_dir"],
        max_workers=1,
        on_progress=on_progress,
        on_log=lambda m: logs.append(m),
    )
    # 测试不写 latest, 用临时目录
    import tempfile
    engine.backup_dir = tempfile.mkdtemp()
    try:
        engine.backup_one(d)
    except Exception as e:
        result_holder["status"] = "失败"
        result_holder["message"] = str(e)
    return jsonify({
        "ok": result_holder.get("status") == "成功",
        "status": result_holder.get("status", "失败"),
        "message": result_holder.get("message", ""),
        "vendor": result_holder.get("vendor", ""),
        "hostname": result_holder.get("real_hostname", ""),
        "logs": logs,
    })


# ====================== 辅助函数 ======================
def _device_from_json(data: dict) -> Device:
    return Device(
        name=data.get("name", ""),
        host=data.get("host", ""),
        port=int(data.get("port", 22) or 22),
        vendor=normalize_vendor(data.get("vendor", "auto")),
        protocol=data.get("protocol", "ssh") or "ssh",
        username=data.get("username", ""),
        password=data.get("password", ""),
        enable_password=data.get("enable_password", ""),
        group=data.get("group", "默认") or "默认",
        timeout=int(data.get("timeout", 30) or 30),
    )


def _device_dict(d: Device) -> dict:
    return {
        "id": getattr(d, "id", None),
        "name": d.name,
        "host": d.host,
        "port": d.port,
        "vendor": d.vendor,
        "vendor_label": VENDOR_LABELS.get(d.vendor, d.vendor),
        "protocol": d.protocol,
        "username": d.username,
        "password": d.password,
        "enable_password": d.enable_password,
        "group": d.group,
        "timeout": d.timeout,
        "status": d.status,
        "message": d.message,
        "last_time": d.last_time,
        "last_file": d.last_file,
        "real_hostname": d.real_hostname,
    }


def _save_last_credentials(data: dict):
    """记住上次输入的凭据, 添加新设备时自动填充"""
    db.update_settings({
        "last_username": data.get("username", ""),
        "last_password": data.get("password", ""),
        "last_enable_password": data.get("enable_password", ""),
        "last_vendor": normalize_vendor(data.get("vendor", "auto")),
        "last_protocol": data.get("protocol", "ssh") or "ssh",
        "last_port": int(data.get("port", 22) or 22),
        "last_group": data.get("group", "默认") or "默认",
    })


@app.route("/api/last_credentials")
def api_last_credentials():
    s = get_settings()
    return jsonify({
        "username": s.get("last_username", ""),
        "password": s.get("last_password", ""),
        "enable_password": s.get("last_enable_password", ""),
        "vendor": s.get("last_vendor", "auto"),
        "protocol": s.get("last_protocol", "ssh"),
        "port": s.get("last_port", 22),
        "group": s.get("last_group", "默认"),
    })


# ====================== 启动 ======================
def init():
    db.init_db()
    # 写入默认设置 (仅当不存在时)
    stored = db.get_all_settings()
    for k, v in DEFAULT_SETTINGS.items():
        if k not in stored:
            db.set_setting(k, v)
    # 一次性迁移: 把历史遗留的绝对路径 backup_dir 转为相对 APP_DIR (通用化部署)
    cur_bd = db.get_setting("backup_dir", "")
    if cur_bd and os.path.isabs(cur_bd):
        try:
            rel = os.path.relpath(cur_bd, APP_DIR)
            # 仅当确实位于 APP_DIR 之下才转相对 (避免误改用户自定义的外部目录)
            if not rel.startswith(".."):
                db.set_setting("backup_dir", rel)
        except ValueError:
            pass
    apply_scheduler()


init()

if __name__ == "__main__":
    print("=" * 56)
    print("  SWBAK 交换机配置备份工具 - Web 版")
    print("  访问地址: http://localhost:5000")
    print("  按 Ctrl+C 停止服务")
    print("=" * 56)
    # threaded=True 支持多请求并发, SSE 长连接不阻塞其他请求
    app.run(host="0.0.0.0", port=5000, threaded=True, debug=False)
