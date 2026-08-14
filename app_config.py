# -*- coding: utf-8 -*-
"""
app_config.py
应用配置管理 - 备份目录、线程数、邮件、定时等设置持久化 (JSON)
"""
import json
import os

CONFIG_FILE = "config.json"

DEFAULT_CONFIG = {
    "backup_dir": "backups",       # 配置保存根目录(相对路径, 相对程序目录)
    "max_workers": 10,             # 并发线程数
    "default_timeout": 30,         # 默认连接超时
    # 邮件通知
    "mail_enabled": False,
    "smtp_host": "",
    "smtp_port": 465,
    "smtp_ssl": True,
    "mail_sender": "",
    "mail_password": "",
    "mail_recipients": "",         # 逗号分隔
    # 定时备份
    "schedule_enabled": False,
    "schedule_mode": "interval",   # interval / daily
    "schedule_interval_hours": 24,
    "schedule_daily_hour": 2,
    # 设备列表文件
    "devices_file": "devices.json",
    # 上次输入的凭据(下次添加设备时自动填充, 重启不丢失)
    "last_username": "",
    "last_password": "",
    "last_enable_password": "",
    "last_vendor": "auto",
    "last_protocol": "ssh",
    "last_port": 22,
    "last_group": "默认",
}


class AppConfig:
    def __init__(self, path: str = None):
        if path is None:
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), CONFIG_FILE)
        self.path = path
        self.data = dict(DEFAULT_CONFIG)
        self.load()

    def load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                self.data.update(loaded)
            except Exception:
                pass
        # 备份目录转绝对路径
        bd = self.data.get("backup_dir", "backups")
        if not os.path.isabs(bd):
            bd = os.path.join(os.path.dirname(os.path.abspath(__file__)), bd)
        self.data["backup_dir"] = bd
        # 设备文件转绝对路径
        df = self.data.get("devices_file", "devices.json")
        if not os.path.isabs(df):
            df = os.path.join(os.path.dirname(os.path.abspath(__file__)), df)
        self.data["devices_file"] = df

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value

    def get_mail_recipients_list(self) -> list:
        raw = self.data.get("mail_recipients", "")
        return [r.strip() for r in raw.replace(";", ",").split(",") if r.strip()]
