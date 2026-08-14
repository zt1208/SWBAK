# -*- coding: utf-8 -*-
"""
gui_dialogs.py
GUI 弹窗: 添加/编辑设备、设置、配置对比、搜索、批量录入
"""
import os
import re
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

from device import Device, VENDOR_TYPES, VENDOR_LABELS

# IPv4 正则 - 用于批量录入校验
_IP_RE = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$")


class DeviceDialog(tk.Toplevel):
    """添加/编辑设备弹窗 (统一入口)

    4 个标签页:
      - 单台添加: 表单逐字段录入 (凭据自动记忆, 下次打开自动填充)
      - 批量录入: 多行文本框粘贴 IP/账号/密码
      - 从文件导入: 选 Excel/CSV/TXT 文件 + 默认凭据补齐
      - 统一密码导入: 粘贴 IP 列表 + 统一凭据
    编辑模式(传入 device)时只显示单台表单
    result: 单个 Device 或 list[Device]
    """

    def __init__(self, parent, device: Device = None, title="添加设备",
                 config=None, initial_tab: int = 0):
        super().__init__(parent)
        self.title(title)
        self.configure(bg="#f8fafc")
        self.result = None
        self._device = device or Device()
        self._is_edit = device is not None
        self._config = config  # AppConfig 实例, 用于记忆凭据

        # 标题横幅
        head = tk.Frame(self, bg="#1e3a8a", height=42)
        head.pack(fill="x")
        head.pack_propagate(False)
        tk.Label(head, text=f"  {title}", font=("Microsoft YaHei", 12, "bold"),
                 fg="white", bg="#1e3a8a").pack(side="left", padx=8)

        # 底部按钮先 pack(side=bottom), 确保始终可见不被 Notebook 挤出
        btn_frame = tk.Frame(self, bg="#f8fafc")
        btn_frame.pack(side="bottom", fill="x", padx=16, pady=(4, 14))
        self._save_btn = tk.Button(btn_frame, text="保存", bg="#2563eb", fg="white",
                  font=("Microsoft YaHei", 10), relief="flat",
                  padx=22, pady=5, cursor="hand2",
                  activebackground="#1d4ed8",
                  command=self._ok)
        self._save_btn.pack(side="right", padx=(6, 0))
        tk.Button(btn_frame, text="取消", bg="#e2e8f0", fg="#1e293b",
                  font=("Microsoft YaHei", 10), relief="flat",
                  padx=22, pady=5, cursor="hand2",
                  activebackground="#cbd5e1",
                  command=self.destroy).pack(side="right")

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=14, pady=(10, 4))

        # Tab1: 单台添加
        self.form_tab = tk.Frame(self.nb, bg="#f8fafc")
        self.nb.add(self.form_tab, text="  单台添加  ")
        self._build_single_form(self.form_tab)

        # 其余 Tab 仅添加模式显示
        if not self._is_edit:
            self.batch_tab = tk.Frame(self.nb, bg="#f8fafc")
            self.nb.add(self.batch_tab, text="  批量录入  ")
            self._build_batch_form(self.batch_tab)

            self.file_tab = tk.Frame(self.nb, bg="#f8fafc")
            self.nb.add(self.file_tab, text="  从文件导入  ")
            self._build_file_tab(self.file_tab)

            self.unified_tab = tk.Frame(self.nb, bg="#f8fafc")
            self.nb.add(self.unified_tab, text="  统一密码导入  ")
            self._build_unified_tab(self.unified_tab)

            # 选中指定 Tab
            try:
                self.nb.select(initial_tab)
            except Exception:
                pass

        if self._is_edit:
            self.resizable(False, False)
        else:
            self.geometry("640x620")
            self.resizable(True, True)
            self.minsize(580, 560)

        self.transient(parent)
        self.grab_set()
        parent.wait_window(self)

    # ---------- 读取记忆的凭据 ----------
    def _get_credential(self, key, fallback=""):
        if self._config:
            v = self._config.get(key, fallback)
            return v if v is not None else fallback
        return fallback

    def _save_credential(self, key, value):
        if self._config:
            self._config.set(key, value)
            self._config.save()

    # ---------- Tab1: 单台表单 ----------
    def _build_single_form(self, parent):
        # 编辑模式用设备自身值; 添加模式用记忆的凭据做默认值
        if self._is_edit:
            d = self._device
        else:
            d = Device(
                username=self._get_credential("last_username"),
                password=self._get_credential("last_password"),
                enable_password=self._get_credential("last_enable_password"),
                vendor=self._get_credential("last_vendor", "auto"),
                protocol=self._get_credential("last_protocol", "ssh"),
                port=self._get_credential("last_port", 22),
                group=self._get_credential("last_group", "默认"),
            )

        fields = [
            ("设备名称:", "name"),
            ("IP 地址:", "host"),
            ("端口:", "port"),
            ("厂商:", "vendor"),
            ("协议:", "protocol"),
            ("用户名:", "username"),
            ("密码:", "password"),
            ("特权密码:", "enable_password"),
            ("分组:", "group"),
            ("超时(秒):", "timeout"),
        ]
        self.vars = {}
        for i, (label, key) in enumerate(fields):
            tk.Label(parent, text=label, font=("Microsoft YaHei", 9),
                    bg="#f8fafc", fg="#334155").grid(row=i, column=0, padx=(8, 8), pady=5, sticky="e")
            val = getattr(d, key)
            if key == "vendor":
                labels = list(VENDOR_LABELS.values())
                label_to_key = {v: k for k, v in VENDOR_LABELS.items()}
                cb = ttk.Combobox(parent, values=labels, state="readonly", width=24)
                cur_key = val if val else "auto"
                cb.set(VENDOR_LABELS.get(cur_key, VENDOR_LABELS["auto"]))
                cb.grid(row=i, column=1, padx=0, pady=5, sticky="w")
                cb._label_to_key = label_to_key
                self.vars[key] = cb
            elif key == "protocol":
                cb = ttk.Combobox(parent, values=["ssh", "telnet"],
                                  state="readonly", width=24)
                cb.set(val if val else "ssh")
                cb.grid(row=i, column=1, padx=0, pady=5, sticky="w")
                self.vars[key] = cb
            else:
                v = tk.StringVar(value=str(val) if val != "" else "")
                e = ttk.Entry(parent, textvariable=v, width=27)
                if key in ("password", "enable_password"):
                    e.config(show="*")
                e.grid(row=i, column=1, padx=0, pady=5, sticky="w")
                self.vars[key] = v

    # ---------- Tab2: 批量录入 ----------
    def _build_batch_form(self, parent):
        tip = ("每行一台设备, 字段用空格 / 逗号 / 制表符分隔\n"
               "格式: IP 用户名 密码 [厂商] [协议] [端口]\n"
               "厂商: auto(自动识别,默认) / huawei / h3c / ruijie   协议: ssh(默认) / telnet\n"
               "# 开头的行会被跳过")
        tk.Label(parent, text=tip, font=("Microsoft YaHei", 9),
                 fg="#475569", bg="#f8fafc", justify="left").pack(anchor="w", padx=10, pady=(8, 4))

        self.batch_text = scrolledtext.ScrolledText(
            parent, font=("Consolas", 10), bg="white", fg="#1e293b",
            relief="solid", bd=1, insertbackground="#1e293b", height=10)
        self.batch_text.pack(fill="both", expand=True, padx=10, pady=4)
        # 用记忆的凭据做示例提示
        lu = self._get_credential("last_username") or "admin"
        lp = self._get_credential("last_password") or "Admin@123"
        self.batch_text.insert("1.0",
                               f"# 示例 (此行以 # 开头会被跳过):\n"
                               f"10.0.0.1 {lu} {lp}\n"
                               f"10.0.0.2 {lu} {lp} huawei ssh\n"
                               f"10.0.0.3 {lu} {lp} h3c telnet 23\n")

        adv = tk.LabelFrame(parent, text="全局默认 (行内未填时使用)", bg="#f8fafc",
                            fg="#334155", font=("Microsoft YaHei", 9))
        adv.pack(fill="x", padx=10, pady=(4, 10))
        tk.Label(adv, text="默认厂商:", bg="#f8fafc").grid(row=0, column=0, padx=6, pady=4, sticky="e")
        self.def_vendor = ttk.Combobox(adv, values=["auto", "huawei", "h3c", "ruijie"],
                                       state="readonly", width=12)
        self.def_vendor.set(self._get_credential("last_vendor", "auto"))
        self.def_vendor.grid(row=0, column=1, padx=6, pady=4)
        tk.Label(adv, text="默认协议:", bg="#f8fafc").grid(row=0, column=2, padx=6, pady=4, sticky="e")
        self.def_protocol = ttk.Combobox(adv, values=["ssh", "telnet"],
                                         state="readonly", width=10)
        self.def_protocol.set(self._get_credential("last_protocol", "ssh"))
        self.def_protocol.grid(row=0, column=3, padx=6, pady=4)

    # ---------- Tab3: 从文件导入 ----------
    def _build_file_tab(self, parent):
        tk.Label(parent, text="从 Excel / CSV / TXT 文件导入设备清单\n"
                 "文件需包含 IP 列(其余字段可选, 缺失字段用下方默认值或自动识别)",
                 font=("Microsoft YaHei", 9), fg="#475569", bg="#f8fafc",
                 justify="left").pack(anchor="w", padx=12, pady=(12, 8))

        f = tk.Frame(parent, bg="#f8fafc")
        f.pack(fill="x", padx=12, pady=4)
        tk.Button(f, text="选择文件...", bg="#2563eb", fg="white",
                  font=("Microsoft YaHei", 9), relief="flat",
                  padx=14, pady=4, cursor="hand2",
                  activebackground="#1d4ed8",
                  command=self._pick_file).pack(side="left")
        self.file_label = tk.Label(parent, text="未选择文件", font=("Microsoft YaHei", 9),
                                   fg="#94a3b8", bg="#f8fafc", anchor="w")
        self.file_label.pack(fill="x", padx=12, pady=4)
        self._file_devices = None

        adv = tk.LabelFrame(parent, text="文件缺失字段的默认值 (自动记忆)", bg="#f8fafc",
                            fg="#334155", font=("Microsoft YaHei", 9))
        adv.pack(fill="x", padx=12, pady=8)
        self.file_user = tk.StringVar(value=self._get_credential("last_username"))
        self.file_pwd = tk.StringVar(value=self._get_credential("last_password"))
        self.file_enable = tk.StringVar(value=self._get_credential("last_enable_password"))
        rows = [("默认用户名:", self.file_user, False),
                ("默认密码:", self.file_pwd, True),
                ("默认特权密码:", self.file_enable, True)]
        for i, (lab, var, is_pwd) in enumerate(rows):
            tk.Label(adv, text=lab, bg="#f8fafc").grid(row=i, column=0, padx=6, pady=4, sticky="e")
            e = ttk.Entry(adv, textvariable=var, width=28)
            if is_pwd:
                e.config(show="*")
            e.grid(row=i, column=1, padx=6, pady=4, sticky="w")

    def _pick_file(self):
        p = filedialog.askopenfilename(
            title="选择设备清单文件",
            filetypes=[("Excel/CSV/TXT", "*.xlsx *.xls *.csv *.txt"),
                       ("所有文件", "*.*")])
        if not p:
            return
        try:
            from importer import import_devices
            devs = import_devices(p)
        except Exception as e:
            messagebox.showerror("导入失败", str(e), parent=self)
            return
        self._file_devices = devs
        if devs:
            self.file_label.config(
                text=f"已加载: {os.path.basename(p)}  ({len(devs)} 台)  → 请点击右下角「保存」完成导入",
                fg="#16a34a")
            # 把保存按钮文字改成明确提示
            self._save_btn.config(text=f"保存(导入 {len(devs)} 台)")
        else:
            self.file_label.config(
                text=f"已加载: {os.path.basename(p)}  但未解析到任何设备, 请检查文件格式",
                fg="#dc2626")

    # ---------- Tab4: 统一密码导入 ----------
    def _build_unified_tab(self, parent):
        tk.Label(parent, text="粘贴 IP 列表(每行一个, 或空格/逗号分隔多个)\n"
                 "所有设备使用下方统一的账号密码",
                 font=("Microsoft YaHei", 9), fg="#475569", bg="#f8fafc",
                 justify="left").pack(anchor="w", padx=12, pady=(12, 6))

        self.ip_text = scrolledtext.ScrolledText(
            parent, font=("Consolas", 10), bg="white", fg="#1e293b",
            relief="solid", bd=1, insertbackground="#1e293b", height=10)
        self.ip_text.pack(fill="both", expand=True, padx=12, pady=4)
        self.ip_text.insert("1.0",
                            "# 粘贴 IP, 每行一个或多个(空格/逗号分隔)\n"
                            "10.0.0.1\n"
                            "10.0.0.2 10.0.0.3\n"
                            "10.0.0.4, 10.0.0.5\n")

        form = tk.LabelFrame(parent, text="统一登录凭据 (自动记忆)", bg="#f8fafc",
                             fg="#334155", font=("Microsoft YaHei", 9))
        form.pack(fill="x", padx=12, pady=(4, 10))

        self.u_user = tk.StringVar(value=self._get_credential("last_username"))
        self.u_pwd = tk.StringVar(value=self._get_credential("last_password"))
        self.u_enable = tk.StringVar(value=self._get_credential("last_enable_password"))
        self.u_vendor = tk.StringVar(value=self._get_credential("last_vendor", "auto"))
        self.u_protocol = tk.StringVar(value=self._get_credential("last_protocol", "ssh"))
        self.u_port = tk.StringVar(value=str(self._get_credential("last_port", 22)))
        self.u_group = tk.StringVar(value=self._get_credential("last_group", "默认"))

        fields = [
            ("用户名:", self.u_user, False, 0, 0),
            ("密码:", self.u_pwd, True, 0, 2),
            ("特权密码:", self.u_enable, True, 1, 0),
            ("厂商:", self.u_vendor, False, 1, 2),
            ("协议:", self.u_protocol, False, 2, 0),
            ("端口:", self.u_port, False, 2, 2),
            ("分组:", self.u_group, False, 3, 0),
        ]
        for lab, var, is_pwd, r, c in fields:
            tk.Label(form, text=lab, bg="#f8fafc").grid(row=r, column=c, padx=6, pady=4, sticky="e")
            if lab in ("厂商:", "协议:"):
                vals = ["auto", "huawei", "h3c", "ruijie"] if lab == "厂商:" else ["ssh", "telnet"]
                cb = ttk.Combobox(form, textvariable=var, values=vals,
                                  state="readonly", width=14)
                cb.grid(row=r, column=c + 1, padx=6, pady=4, sticky="w")
            else:
                e = ttk.Entry(form, textvariable=var, width=16)
                if is_pwd:
                    e.config(show="*")
                e.grid(row=r, column=c + 1, padx=6, pady=4, sticky="w")

    # ---------- 确定 ----------
    def _ok(self):
        tab = self.nb.index("current")
        if self._is_edit or tab == 0:
            self._ok_single()
        elif tab == 1:
            self._ok_batch()
        elif tab == 2:
            self._ok_file()
        else:
            self._ok_unified()

    def _ok_single(self):
        host = self.vars["host"].get().strip()
        if not host:
            messagebox.showerror("错误", "IP 地址不能为空", parent=self)
            return
        try:
            port = int(self.vars["port"].get().strip() or "0")
        except ValueError:
            messagebox.showerror("错误", "端口必须为数字", parent=self)
            return
        try:
            timeout = int(self.vars["timeout"].get().strip() or "30")
        except ValueError:
            timeout = 30

        vendor_cb = self.vars["vendor"]
        vendor_label = vendor_cb.get()
        vendor_key = vendor_cb._label_to_key.get(vendor_label, "auto")
        protocol = self.vars["protocol"].get()
        username = self.vars["username"].get().strip()
        password = self.vars["password"].get()
        enable = self.vars["enable_password"].get()
        group = self.vars["group"].get().strip() or "默认"

        # 记忆凭据 (重启不丢失)
        self._save_credential("last_username", username)
        self._save_credential("last_password", password)
        self._save_credential("last_enable_password", enable)
        self._save_credential("last_vendor", vendor_key)
        self._save_credential("last_protocol", protocol)
        self._save_credential("last_port", port)
        self._save_credential("last_group", group)

        self.result = Device(
            name=self.vars["name"].get().strip(), host=host, port=port,
            vendor=vendor_key, protocol=protocol, username=username,
            password=password, enable_password=enable, group=group,
            timeout=timeout, status=self._device.status,
            message=self._device.message, last_time=self._device.last_time,
            last_file=self._device.last_file, real_hostname=self._device.real_hostname,
        )
        self.destroy()

    def _ok_batch(self):
        content = self.batch_text.get("1.0", "end")
        def_vendor = self.def_vendor.get()
        def_protocol = self.def_protocol.get()
        devices, bad = [], []
        for ln, raw in enumerate(content.splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = re.split(r"[\s,，\t]+", line)
            parts = [p for p in parts if p]
            if len(parts) < 3:
                bad.append(f"第{ln}行: 字段不足3个 ('{raw}')")
                continue
            host, user, pwd = parts[0], parts[1], parts[2]
            if not _IP_RE.match(host):
                bad.append(f"第{ln}行: '{host}' 不是合法 IP")
                continue
            vendor, protocol = def_vendor, def_protocol
            port = 22 if protocol == "ssh" else 23
            if len(parts) > 3 and parts[3]:
                v = parts[3].lower()
                if v in ("华为", "hw"): vendor = "huawei"
                elif v in ("华三", "h3c", "hp"): vendor = "h3c"
                elif v in ("锐捷", "ruijie", "rj"): vendor = "ruijie"
                elif v in ("自动", "auto"): vendor = "auto"
                else: vendor = v
            if len(parts) > 4 and parts[4]:
                p = parts[4].lower()
                if p in ("ssh", "telnet"):
                    protocol = p
                    port = 23 if protocol == "telnet" else 22
            if len(parts) > 5 and parts[5]:
                try: port = int(parts[5])
                except ValueError: pass
            devices.append(Device(host=host, username=user, password=pwd,
                                  vendor=vendor, protocol=protocol, port=port))
        if bad:
            if not messagebox.askyesno("部分行格式有误",
                    f"共 {len(bad)} 行无法解析:\n\n" + "\n".join(bad[:10]) +
                    ("\n..." if len(bad) > 10 else "") +
                    f"\n\n共解析到 {len(devices)} 台有效设备, 是否添加?", parent=self):
                return
        if not devices:
            messagebox.showwarning("提示", "未解析到任何有效设备", parent=self)
            return
        # 记忆默认值
        self._save_credential("last_vendor", def_vendor)
        self._save_credential("last_protocol", def_protocol)
        self.result = devices
        self.destroy()

    def _ok_file(self):
        if self._file_devices is None:
            messagebox.showwarning("提示", "请先选择文件", parent=self)
            return
        if len(self._file_devices) == 0:
            messagebox.showwarning("提示",
                "文件已选择但未解析到任何设备\n请检查文件格式(需包含 IP 列)", parent=self)
            return
        du = self.file_user.get().strip()
        dp = self.file_pwd.get()
        de = self.file_enable.get()
        for d in self._file_devices:
            if not d.username and du: d.username = du
            if not d.password and dp: d.password = dp
            if not d.enable_password and de: d.enable_password = de
        # 记忆
        self._save_credential("last_username", du)
        self._save_credential("last_password", dp)
        self._save_credential("last_enable_password", de)
        self.result = self._file_devices
        self.destroy()

    def _ok_unified(self):
        content = self.ip_text.get("1.0", "end")
        ips = _IP_EXTRACT.findall(content)
        seen, uniq = set(), []
        for ip in ips:
            if ip not in seen:
                seen.add(ip)
                uniq.append(ip)
        if not uniq:
            messagebox.showwarning("提示", "未识别到任何 IP 地址", parent=self)
            return
        user = self.u_user.get().strip()
        pwd = self.u_pwd.get()
        if not user or not pwd:
            if not messagebox.askyesno("确认", "用户名或密码为空, 仍要继续?", parent=self):
                return
        enable = self.u_enable.get()
        vendor = self.u_vendor.get() or "auto"
        protocol = self.u_protocol.get() or "ssh"
        group = self.u_group.get().strip() or "默认"
        try:
            port = int(self.u_port.get().strip() or "22")
        except ValueError:
            port = 22
        # 记忆
        self._save_credential("last_username", user)
        self._save_credential("last_password", pwd)
        self._save_credential("last_enable_password", enable)
        self._save_credential("last_vendor", vendor)
        self._save_credential("last_protocol", protocol)
        self._save_credential("last_port", port)
        self._save_credential("last_group", group)
        self.result = [Device(host=ip, username=user, password=pwd,
                              enable_password=enable, vendor=vendor,
                              protocol=protocol, port=port, group=group)
                       for ip in uniq]
        self.destroy()


class SettingsDialog(tk.Toplevel):
    """设置弹窗: 备份目录/线程/邮件/定时"""

    def __init__(self, parent, config):
        super().__init__(parent)
        self.title("设置")
        self.resizable(False, False)
        self.config = config
        self.result = False

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=10)

        self._build_general_tab(nb)
        self._build_mail_tab(nb)
        self._build_schedule_tab(nb)

        btn = ttk.Frame(self)
        btn.pack(fill="x", padx=10, pady=10)
        ttk.Button(btn, text="保存", command=self._save).pack(side="right", padx=5)
        ttk.Button(btn, text="取消", command=self.destroy).pack(side="right", padx=5)

        self.transient(parent)
        self.grab_set()
        parent.wait_window(self)

    def _build_general_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="通用")
        f.columnconfigure(1, weight=1)

        ttk.Label(f, text="备份保存目录:").grid(row=0, column=0, sticky="e", padx=8, pady=8)
        self.dir_var = tk.StringVar(value=self.config.get("backup_dir", ""))
        de = ttk.Entry(f, textvariable=self.dir_var)
        de.grid(row=0, column=1, sticky="we", padx=8)
        ttk.Button(f, text="浏览...", command=self._browse_dir).grid(row=0, column=2, padx=8)

        ttk.Label(f, text="并发线程数:").grid(row=1, column=0, sticky="e", padx=8, pady=8)
        self.threads_var = tk.StringVar(value=str(self.config.get("max_workers", 10)))
        ttk.Entry(f, textvariable=self.threads_var, width=10).grid(row=1, column=1, sticky="w", padx=8)

        ttk.Label(f, text="默认超时(秒):").grid(row=2, column=0, sticky="e", padx=8, pady=8)
        self.timeout_var = tk.StringVar(value=str(self.config.get("default_timeout", 30)))
        ttk.Entry(f, textvariable=self.timeout_var, width=10).grid(row=2, column=1, sticky="w", padx=8)

    def _build_mail_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="邮件通知")
        self.mail_enabled = tk.BooleanVar(value=self.config.get("mail_enabled", False))
        ttk.Checkbutton(f, text="备份完成后发送邮件报告",
                        variable=self.mail_enabled).grid(row=0, column=0, columnspan=2, padx=8, pady=8, sticky="w")

        labels = ["SMTP 服务器:", "端口:", "发件邮箱:", "授权码/密码:", "收件人(逗号分隔):"]
        keys = ["smtp_host", "smtp_port", "mail_sender", "mail_password", "mail_recipients"]
        self.mail_vars = {}
        for i, (label, key) in enumerate(zip(labels, keys), 1):
            ttk.Label(f, text=label).grid(row=i, column=0, sticky="e", padx=8, pady=5)
            v = tk.StringVar(value=str(self.config.get(key, "")))
            e = ttk.Entry(f, textvariable=v, width=35)
            if key == "mail_password":
                e.config(show="*")
            e.grid(row=i, column=1, padx=8, pady=5)
            self.mail_vars[key] = v

        self.smtp_ssl = tk.BooleanVar(value=self.config.get("smtp_ssl", True))
        ttk.Checkbutton(f, text="使用 SSL", variable=self.smtp_ssl).grid(
            row=len(labels) + 1, column=0, columnspan=2, padx=8, sticky="w")

    def _build_schedule_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="定时备份")
        self.sched_enabled = tk.BooleanVar(value=self.config.get("schedule_enabled", False))
        ttk.Checkbutton(f, text="启用定时自动备份",
                        variable=self.sched_enabled).grid(row=0, column=0, columnspan=2, padx=8, pady=8, sticky="w")

        self.sched_mode = tk.StringVar(value=self.config.get("schedule_mode", "interval"))
        ttk.Radiobutton(f, text="每隔 N 小时", value="interval",
                        variable=self.sched_mode).grid(row=1, column=0, padx=8, sticky="w")
        self.interval_var = tk.StringVar(value=str(self.config.get("schedule_interval_hours", 24)))
        ttk.Entry(f, textvariable=self.interval_var, width=8).grid(row=1, column=1, sticky="w", pady=5)

        ttk.Radiobutton(f, text="每天定点", value="daily",
                        variable=self.sched_mode).grid(row=2, column=0, padx=8, sticky="w")
        self.daily_var = tk.StringVar(value=str(self.config.get("schedule_daily_hour", 2)))
        ttk.Entry(f, textvariable=self.daily_var, width=8).grid(row=2, column=1, sticky="w", pady=5)
        ttk.Label(f, text="点(0-23)").grid(row=2, column=2, sticky="w")

    def _browse_dir(self):
        d = filedialog.askdirectory(parent=self, initialdir=self.dir_var.get())
        if d:
            self.dir_var.set(d)

    def _save(self):
        self.config.set("backup_dir", self.dir_var.get().strip())
        try:
            self.config.set("max_workers", int(self.threads_var.get()))
        except ValueError:
            self.config.set("max_workers", 10)
        try:
            self.config.set("default_timeout", int(self.timeout_var.get()))
        except ValueError:
            self.config.set("default_timeout", 30)

        self.config.set("mail_enabled", self.mail_enabled.get())
        for k, v in self.mail_vars.items():
            if k == "smtp_port":
                try:
                    self.config.set("smtp_port", int(v.get()))
                except ValueError:
                    self.config.set("smtp_port", 465)
            else:
                self.config.set(k, v.get())
        self.config.set("smtp_ssl", self.smtp_ssl.get())

        self.config.set("schedule_enabled", self.sched_enabled.get())
        self.config.set("schedule_mode", self.sched_mode.get())
        try:
            self.config.set("schedule_interval_hours", int(self.interval_var.get()))
        except ValueError:
            self.config.set("schedule_interval_hours", 24)
        try:
            h = int(self.daily_var.get())
            self.config.set("schedule_daily_hour", max(0, min(23, h)))
        except ValueError:
            self.config.set("schedule_daily_hour", 2)

        self.config.save()
        self.result = True
        self.destroy()


class CompareDialog(tk.Toplevel):
    """配置对比窗口"""

    def __init__(self, parent, backup_dir: str):
        super().__init__(parent)
        self.title("配置对比")
        self.geometry("900x600")
        self.backup_dir = backup_dir

        top = ttk.Frame(self)
        top.pack(fill="x", padx=10, pady=5)
        ttk.Label(top, text="选择设备目录:").pack(side="left")

        # 递归列出所有含配置文件的设备目录 (支持 分组/设备名 两层结构)
        devices = []
        if os.path.isdir(backup_dir):
            for group_name in sorted(os.listdir(backup_dir)):
                group_path = os.path.join(backup_dir, group_name)
                if not os.path.isdir(group_path):
                    continue
                # 检查是否直接包含配置文件 (旧的单层结构)
                has_cfg = any(f.endswith((".txt", ".cfg")) and not f.startswith("latest")
                              for f in os.listdir(group_path))
                if has_cfg:
                    devices.append(group_name)
                # 检查子目录 (新的两层结构: 分组/设备名)
                for dev_name in sorted(os.listdir(group_path)):
                    dev_path = os.path.join(group_path, dev_name)
                    if os.path.isdir(dev_path):
                        devices.append(f"{group_name}/{dev_name}")
        self.dev_combo = ttk.Combobox(top, values=devices, state="readonly", width=40)
        self.dev_combo.pack(side="left", padx=5)
        if devices:
            self.dev_combo.current(0)
        ttk.Button(top, text="加载", command=self._load_versions).pack(side="left", padx=5)

        mid = ttk.Frame(self)
        mid.pack(fill="x", padx=10, pady=5)
        ttk.Label(mid, text="旧版本:").pack(side="left")
        self.old_combo = ttk.Combobox(mid, state="readonly", width=40)
        self.old_combo.pack(side="left", padx=5)
        ttk.Label(mid, text="新版本:").pack(side="left", padx=(10, 0))
        self.new_combo = ttk.Combobox(mid, state="readonly", width=40)
        self.new_combo.pack(side="left", padx=5)
        ttk.Button(mid, text="对比", command=self._compare).pack(side="left", padx=5)

        info = ttk.Frame(self)
        info.pack(fill="x", padx=10)
        self.info_var = tk.StringVar(value="请选择两个版本进行对比")
        ttk.Label(info, textvariable=self.info_var, foreground="#1f6feb").pack(anchor="w")

        self.text = scrolledtext.ScrolledText(self, font=("Consolas", 10), wrap="none")
        self.text.pack(fill="both", expand=True, padx=10, pady=5)
        self.text.tag_config("add", foreground="#28a745")
        self.text.tag_config("del", foreground="#dc3545")
        self.text.tag_config("hdr", foreground="#9999ff")
        self.text.config(state="disabled")

        self.transient(parent)

    def _load_versions(self):
        dev = self.dev_combo.get()
        if not dev:
            return
        from config_compare import list_backups
        # dev 可能是 "分组/设备名" 或单层 "设备名"
        self._dev_dir = os.path.join(self.backup_dir, dev)
        files = list_backups(self._dev_dir)
        names = [f[0] for f in files]
        self.old_combo["values"] = names
        self.new_combo["values"] = names
        if len(names) >= 1:
            self.new_combo.current(0)
        if len(names) >= 2:
            self.old_combo.current(1)

    def _compare(self):
        old = self.old_combo.get()
        new = self.new_combo.get()
        if not old or not new or old == new:
            messagebox.showwarning("提示", "请选择两个不同的版本", parent=self)
            return
        from config_compare import compare
        old_p = os.path.join(self._dev_dir, old)
        new_p = os.path.join(self._dev_dir, new)
        r = compare(old_p, new_p)
        self.info_var.set(
            f"新增 {r['added']} 行, 删除 {r['removed']} 行 | "
            f"旧: {r['old_mtime']} | 新: {r['new_mtime']}"
        )
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        for line in r["diff_text"].splitlines():
            if line.startswith("+++") or line.startswith("---"):
                self.text.insert("end", line + "\n", "hdr")
            elif line.startswith("+"):
                self.text.insert("end", line + "\n", "add")
            elif line.startswith("-"):
                self.text.insert("end", line + "\n", "del")
            else:
                self.text.insert("end", line + "\n")
        self.text.config(state="disabled")


class SearchDialog(tk.Toplevel):
    """配置全文搜索窗口"""

    def __init__(self, parent, backup_dir: str):
        super().__init__(parent)
        self.title("配置搜索")
        self.geometry("850x550")
        self.backup_dir = backup_dir

        top = ttk.Frame(self)
        top.pack(fill="x", padx=10, pady=5)
        ttk.Label(top, text="关键字:").pack(side="left")
        self.kw = tk.StringVar()
        ttk.Entry(top, textvariable=self.kw, width=30).pack(side="left", padx=5)
        ttk.Button(top, text="搜索", command=self._search).pack(side="left")

        cols = ("file", "line", "content")
        self.tree = ttk.Treeview(self, columns=cols, show="headings")
        self.tree.heading("file", text="文件")
        self.tree.heading("line", text="行号")
        self.tree.heading("content", text="内容")
        self.tree.column("file", width=250)
        self.tree.column("line", width=60)
        self.tree.column("content", width=500)
        self.tree.pack(fill="both", expand=True, padx=10, pady=5)

        self.transient(parent)

    def _search(self):
        kw = self.kw.get().strip()
        if not kw:
            return
        from config_compare import search_in_configs
        self.tree.delete(*self.tree.get_children())
        results = search_in_configs(self.backup_dir, kw)
        for p, no, line in results:
            self.tree.insert("", "end", values=(os.path.basename(os.path.dirname(p)) + "/" +
                                                os.path.basename(p), no, line))
        if not results:
            self.tree.insert("", "end", values=("(无结果)", "", ""))


class BatchEntryDialog(tk.Toplevel):
    """批量录入对话框 - 文本框粘贴多行设备信息一次性添加

    支持每行格式 (空格 / 逗号 / 制表符 分隔):
      IP 用户名 密码
      IP 用户名 密码 厂商
      IP 用户名 密码 厂商 协议
      IP 用户名 密码 厂商 协议 端口

    厂商可填: auto / huawei / h3c / ruijie (或中文 华为/华三/锐捷), 默认 auto
    协议可填: ssh / telnet, 默认 ssh
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.title("批量录入设备")
        self.geometry("680x520")
        self.result: list = []
        self.configure(bg="#f8fafc")

        # 标题区
        head = tk.Frame(self, bg="#2563eb", height=50)
        head.pack(fill="x")
        head.pack_propagate(False)
        tk.Label(head, text="  批量录入设备", font=("Microsoft YaHei", 13, "bold"),
                 fg="white", bg="#2563eb").pack(side="left", padx=10, pady=10)

        body = tk.Frame(self, bg="#f8fafc")
        body.pack(fill="both", expand=True, padx=14, pady=10)

        # 底部按钮先 pack(side=bottom), 确保始终可见
        btn = tk.Frame(body, bg="#f8fafc")
        btn.pack(side="bottom", fill="x", pady=(6, 0))
        tk.Button(btn, text="添加到列表", bg="#2563eb", fg="white",
                  font=("Microsoft YaHei", 10), relief="flat",
                  padx=14, pady=4, cursor="hand2",
                  command=self._ok).pack(side="right", padx=6)
        tk.Button(btn, text="取消", bg="#e2e8f0", fg="#1e293b",
                  font=("Microsoft YaHei", 10), relief="flat",
                  padx=14, pady=4, cursor="hand2",
                  command=self.destroy).pack(side="right")

        # 全局默认设置 (应用到所有行, 留空则用行内值或默认)
        adv = tk.LabelFrame(body, text="全局默认 (留空=使用行内值)", bg="#f8fafc",
                            fg="#334155", font=("Microsoft YaHei", 9))
        adv.pack(side="bottom", fill="x", pady=(8, 4))
        tk.Label(adv, text="默认厂商:", bg="#f8fafc").grid(row=0, column=0, padx=6, pady=4, sticky="e")
        self.def_vendor = ttk.Combobox(adv, values=["auto", "huawei", "h3c", "ruijie"],
                                       state="readonly", width=12)
        self.def_vendor.set("auto")
        self.def_vendor.grid(row=0, column=1, padx=6, pady=4)
        tk.Label(adv, text="默认协议:", bg="#f8fafc").grid(row=0, column=2, padx=6, pady=4, sticky="e")
        self.def_protocol = ttk.Combobox(adv, values=["ssh", "telnet"],
                                         state="readonly", width=10)
        self.def_protocol.set("ssh")
        self.def_protocol.grid(row=0, column=3, padx=6, pady=4)

        # 说明
        tip = ("每行一台设备, 字段用空格 / 逗号 / 制表符分隔\n"
               "格式: IP 用户名 密码 [厂商] [协议] [端口]\n"
               "厂商: auto(自动识别,默认) / huawei / h3c / ruijie   协议: ssh(默认) / telnet")
        tk.Label(body, text=tip, font=("Microsoft YaHei", 9),
                 fg="#475569", bg="#f8fafc", justify="left").pack(anchor="w", pady=(0, 6))

        # 输入框
        self.text = scrolledtext.ScrolledText(body, font=("Consolas", 10),
                                              bg="white", fg="#1e293b",
                                              relief="solid", bd=1,
                                              insertbackground="#1e293b", height=10)
        self.text.pack(fill="both", expand=True)
        self.text.insert("1.0",
                         "# 示例 (此行以 # 开头会被跳过):\n"
                         "10.0.0.1 admin Admin@123\n"
                         "10.0.0.2 admin Admin@123 huawei ssh\n"
                         "10.0.0.3 admin Admin@123 h3c telnet 23\n"
                         "10.0.0.4 admin Admin@123 ruijie ssh 22\n")

        self.transient(parent)
        self.grab_set()
        parent.wait_window(self)

    def _ok(self):
        content = self.text.get("1.0", "end")
        def_vendor = self.def_vendor.get()
        def_protocol = self.def_protocol.get()
        devices = []
        bad = []
        for ln, raw in enumerate(content.splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = re.split(r"[\s,，\t]+", line)
            parts = [p for p in parts if p]
            if len(parts) < 3:
                bad.append(f"第{ln}行: 字段不足3个 ('{raw}')")
                continue
            host, user, pwd = parts[0], parts[1], parts[2]
            if not _IP_RE.match(host):
                bad.append(f"第{ln}行: '{host}' 不是合法 IP")
                continue

            vendor = def_vendor
            protocol = def_protocol
            port = 22 if protocol == "ssh" else 23
            if len(parts) > 3 and parts[3]:
                v = parts[3].lower()
                if v in ("华为", "hw"):
                    vendor = "huawei"
                elif v in ("华三", "h3c", "hp"):
                    vendor = "h3c"
                elif v in ("锐捷", "ruijie", "rj"):
                    vendor = "ruijie"
                elif v in ("自动", "auto"):
                    vendor = "auto"
                else:
                    vendor = v
            if len(parts) > 4 and parts[4]:
                p = parts[4].lower()
                if p in ("ssh", "telnet"):
                    protocol = p
                    port = 23 if protocol == "telnet" else 22
            if len(parts) > 5 and parts[5]:
                try:
                    port = int(parts[5])
                except ValueError:
                    pass

            devices.append(Device(host=host, username=user, password=pwd,
                                  vendor=vendor, protocol=protocol, port=port))

        if bad:
            if not messagebox.askyesno(
                    "部分行格式有误",
                    f"共 {len(bad)} 行无法解析:\n\n" + "\n".join(bad[:10]) +
                    ("\n..." if len(bad) > 10 else "") +
                    f"\n\n共解析到 {len(devices)} 台有效设备, 是否添加?",
                    parent=self):
                return
        if not devices:
            messagebox.showwarning("提示", "未解析到任何有效设备", parent=self)
            return

        self.result = devices
        self.destroy()


# 从文本中提取所有 IPv4 地址 (支持每行一个 / 空格 / 逗号 / 混排)
_IP_EXTRACT = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


class ImportDialog(tk.Toplevel):
    """批量导入对话框 - 两种模式

    Tab1 从文件导入: 选择 Excel/CSV/TXT 文件 (文件里可含完整字段)
    Tab2 统一密码导入: 粘贴 IP 列表 + 统一输入一次账号密码 (适用所有设备同密码场景)
    result: list[Device] 或 None
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.title("批量导入设备")
        self.geometry("620x560")
        self.configure(bg="#f8fafc")
        self.result = None
        self._file_devices = None  # Tab1 解析出的设备暂存

        # 标题横幅
        head = tk.Frame(self, bg="#1e3a8a", height=42)
        head.pack(fill="x")
        head.pack_propagate(False)
        tk.Label(head, text="  批量导入设备", font=("Microsoft YaHei", 12, "bold"),
                 fg="white", bg="#1e3a8a").pack(side="left", padx=8)

        # 底部按钮先 pack(side=bottom), 确保始终可见
        btn_frame = tk.Frame(self, bg="#f8fafc")
        btn_frame.pack(side="bottom", fill="x", padx=16, pady=(4, 14))
        tk.Button(btn_frame, text="导入", bg="#2563eb", fg="white",
                  font=("Microsoft YaHei", 10), relief="flat",
                  padx=22, pady=5, cursor="hand2",
                  activebackground="#1d4ed8",
                  command=self._ok).pack(side="right", padx=(6, 0))
        tk.Button(btn_frame, text="取消", bg="#e2e8f0", fg="#1e293b",
                  font=("Microsoft YaHei", 10), relief="flat",
                  padx=22, pady=5, cursor="hand2",
                  activebackground="#cbd5e1",
                  command=self.destroy).pack(side="right")

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=14, pady=(10, 4))

        # Tab1: 从文件导入
        self.file_tab = tk.Frame(self.nb, bg="#f8fafc")
        self.nb.add(self.file_tab, text="  从文件导入  ")
        self._build_file_tab(self.file_tab)

        # Tab2: 统一密码导入
        self.unified_tab = tk.Frame(self.nb, bg="#f8fafc")
        self.nb.add(self.unified_tab, text="  统一密码导入  ")
        self._build_unified_tab(self.unified_tab)

        self.transient(parent)
        self.grab_set()
        parent.wait_window(self)

    # ---------- Tab1: 从文件导入 ----------
    def _build_file_tab(self, parent):
        tk.Label(parent, text="从 Excel / CSV / TXT 文件导入设备清单\n"
                 "文件需包含 IP 列(其余字段可选, 缺失字段用下方默认值或自动识别)",
                 font=("Microsoft YaHei", 9), fg="#475569", bg="#f8fafc",
                 justify="left").pack(anchor="w", padx=12, pady=(12, 8))

        f = tk.Frame(parent, bg="#f8fafc")
        f.pack(fill="x", padx=12, pady=4)
        tk.Button(f, text="选择文件...", bg="#2563eb", fg="white",
                  font=("Microsoft YaHei", 9), relief="flat",
                  padx=14, pady=4, cursor="hand2",
                  activebackground="#1d4ed8",
                  command=self._pick_file).pack(side="left")
        self.file_label = tk.Label(parent, text="未选择文件", font=("Microsoft YaHei", 9),
                                   fg="#94a3b8", bg="#f8fafc", anchor="w")
        self.file_label.pack(fill="x", padx=12, pady=4)

        # 默认账号密码(文件里缺失时用)
        adv = tk.LabelFrame(parent, text="文件缺失字段的默认值", bg="#f8fafc",
                            fg="#334155", font=("Microsoft YaHei", 9))
        adv.pack(fill="x", padx=12, pady=8)
        self.file_user = tk.StringVar()
        self.file_pwd = tk.StringVar()
        self.file_enable = tk.StringVar()
        rows = [("默认用户名:", self.file_user, False),
                ("默认密码:", self.file_pwd, True),
                ("默认特权密码:", self.file_enable, True)]
        for i, (lab, var, is_pwd) in enumerate(rows):
            tk.Label(adv, text=lab, bg="#f8fafc").grid(row=i, column=0, padx=6, pady=4, sticky="e")
            e = ttk.Entry(adv, textvariable=var, width=28)
            if is_pwd:
                e.config(show="*")
            e.grid(row=i, column=1, padx=6, pady=4, sticky="w")

    def _pick_file(self):
        p = filedialog.askopenfilename(
            title="选择设备清单文件",
            filetypes=[("Excel/CSV/TXT", "*.xlsx *.xls *.csv *.txt"),
                       ("所有文件", "*.*")])
        if not p:
            return
        try:
            from importer import import_devices
            devs = import_devices(p)
        except Exception as e:
            messagebox.showerror("导入失败", str(e), parent=self)
            return
        self._file_devices = devs
        self._file_path = p
        self.file_label.config(text=f"已加载: {os.path.basename(p)}  ({len(devs)} 台)",
                               fg="#16a34a")

    # ---------- Tab2: 统一密码导入 ----------
    def _build_unified_tab(self, parent):
        tk.Label(parent, text="粘贴 IP 列表(每行一个, 或空格/逗号分隔多个)\n"
                 "所有设备使用下方统一的账号密码",
                 font=("Microsoft YaHei", 9), fg="#475569", bg="#f8fafc",
                 justify="left").pack(anchor="w", padx=12, pady=(12, 6))

        self.ip_text = scrolledtext.ScrolledText(
            parent, font=("Consolas", 10), bg="white", fg="#1e293b",
            relief="solid", bd=1, insertbackground="#1e293b", height=10)
        self.ip_text.pack(fill="both", expand=True, padx=12, pady=4)
        self.ip_text.insert("1.0",
                            "# 粘贴 IP, 每行一个或多个(空格/逗号分隔)\n"
                            "10.0.0.1\n"
                            "10.0.0.2 10.0.0.3\n"
                            "10.0.0.4, 10.0.0.5\n")

        # 统一账号密码字段
        form = tk.LabelFrame(parent, text="统一登录凭据 (应用到所有 IP)", bg="#f8fafc",
                             fg="#334155", font=("Microsoft YaHei", 9))
        form.pack(fill="x", padx=12, pady=(4, 10))

        self.u_user = tk.StringVar()
        self.u_pwd = tk.StringVar()
        self.u_enable = tk.StringVar()
        self.u_vendor = tk.StringVar(value="auto")
        self.u_protocol = tk.StringVar(value="ssh")
        self.u_port = tk.StringVar(value="22")
        self.u_group = tk.StringVar(value="默认")

        fields = [
            ("用户名:", self.u_user, False, 0, 0),
            ("密码:", self.u_pwd, True, 0, 2),
            ("特权密码:", self.u_enable, True, 1, 0),
            ("厂商:", self.u_vendor, False, 1, 2),
            ("协议:", self.u_protocol, False, 2, 0),
            ("端口:", self.u_port, False, 2, 2),
            ("分组:", self.u_group, False, 3, 0),
        ]
        for lab, var, is_pwd, r, c in fields:
            tk.Label(form, text=lab, bg="#f8fafc").grid(row=r, column=c, padx=6, pady=4, sticky="e")
            if lab in ("厂商:", "协议:"):
                if lab == "厂商:":
                    vals = ["auto", "huawei", "h3c", "ruijie"]
                else:
                    vals = ["ssh", "telnet"]
                cb = ttk.Combobox(form, textvariable=var, values=vals,
                                  state="readonly", width=14)
                cb.grid(row=r, column=c + 1, padx=6, pady=4, sticky="w")
            else:
                e = ttk.Entry(form, textvariable=var, width=16)
                if is_pwd:
                    e.config(show="*")
                e.grid(row=r, column=c + 1, padx=6, pady=4, sticky="w")

    # ---------- 确定 ----------
    def _ok(self):
        tab = self.nb.index("current")
        if tab == 0:
            self._ok_file()
        else:
            self._ok_unified()

    def _ok_file(self):
        if not self._file_devices:
            messagebox.showwarning("提示", "请先选择文件", parent=self)
            return
        # 用默认值补齐文件里缺失的账号密码
        du = self.file_user.get().strip()
        dp = self.file_pwd.get()
        de = self.file_enable.get()
        for d in self._file_devices:
            if not d.username and du:
                d.username = du
            if not d.password and dp:
                d.password = dp
            if not d.enable_password and de:
                d.enable_password = de
        self.result = self._file_devices
        self.destroy()

    def _ok_unified(self):
        content = self.ip_text.get("1.0", "end")
        ips = _IP_EXTRACT.findall(content)
        # 去重保序
        seen = set()
        uniq = []
        for ip in ips:
            if ip not in seen:
                seen.add(ip)
                uniq.append(ip)
        if not uniq:
            messagebox.showwarning("提示", "未识别到任何 IP 地址", parent=self)
            return

        user = self.u_user.get().strip()
        pwd = self.u_pwd.get()
        if not user or not pwd:
            if not messagebox.askyesno("确认", "用户名或密码为空, 仍要继续?",
                                       parent=self):
                return
        enable = self.u_enable.get()
        vendor = self.u_vendor.get() or "auto"
        protocol = self.u_protocol.get() or "ssh"
        group = self.u_group.get().strip() or "默认"
        try:
            port = int(self.u_port.get().strip() or "22")
        except ValueError:
            port = 22

        devices = [Device(host=ip, username=user, password=pwd,
                          enable_password=enable, vendor=vendor,
                          protocol=protocol, port=port, group=group)
                   for ip in uniq]
        self.result = devices
        self.destroy()
