# -*- coding: utf-8 -*-
"""
device.py
设备数据模型 - 描述一台交换机的所有连接与元数据信息
"""
from dataclasses import dataclass, asdict, fields
from datetime import datetime
import json
import os

# 支持的厂商及对应 netmiko 设备类型
# vendor="auto" 时, 连接阶段用 netmiko SSHDetect 自动识别,
# 识别后再切换到对应厂商命令抓取配置
VENDOR_TYPES = {
    "auto": {
        "ssh": "autodetect",
        "telnet": "autodetect",
        "show_cmd": "",          # 由识别结果动态决定
        "paging_cmd": "",
        "name_cmd": "",
    },
    "huawei": {
        "ssh": "huawei",
        "telnet": "huawei_telnet",
        "show_cmd": "display current-configuration",
        "paging_cmd": "screen-length 0 temporary",
        "name_cmd": "display current-configuration | include sysname",
    },
    "h3c": {
        "ssh": "hp_comware",
        "telnet": "hp_comware_telnet",
        "show_cmd": "display current-configuration",
        "paging_cmd": "screen-length disable",
        "name_cmd": "display current-configuration | include sysname",
    },
    "ruijie": {
        "ssh": "ruijie_os",
        "telnet": "ruijie_os_telnet",
        "show_cmd": "show running-config",
        "paging_cmd": "terminal length 0",
        "name_cmd": "show running-config | include hostname",
    },
}

# netmiko 探测出的 device_type -> 我们的 vendor 名
# SSHDetect 可能返回 huawei / hp_comware / ruijie_os 等
DEVICE_TYPE_TO_VENDOR = {
    "huawei": "huawei",
    "huawei_telnet": "huawei",
    "hp_comware": "h3c",
    "hp_comware_telnet": "h3c",
    "ruijie_os": "ruijie",
    "ruijie_os_telnet": "ruijie",
}

# 给 GUI 下拉框用的人类可读名称
VENDOR_LABELS = {
    "auto": "自动识别 (auto)",
    "huawei": "华为 (Huawei)",
    "h3c": "华三 (H3C)",
    "ruijie": "锐捷 (Ruijie)",
}

# 厂商别名 -> 内部 key (兼容中文标签 / 缩写 / 大小写)
# 防止 GUI 下拉的中文标签或用户手填的别名被当作 vendor 存入
_VENDOR_ALIASES = {
    "auto": "auto", "automatic": "auto", "自动": "auto", "自动识别": "auto",
    "自动识别 (auto)": "auto", "auto (自动识别)": "auto",
    "huawei": "huawei", "hw": "huawei", "华为": "huawei",
    "华为 (huawei)": "huawei", "huawei (华为)": "huawei",
    "h3c": "h3c", "hp": "h3c", "h3c/华三": "h3c", "华三": "h3c", "华三 (h3c)": "h3c",
    "h3c (华三)": "h3c", "comware": "h3c",
    "ruijie": "ruijie", "rj": "ruijie", "锐捷": "ruijie",
    "锐捷 (ruijie)": "ruijie", "ruijie (锐捷)": "ruijie",
}


def normalize_vendor(vendor: str) -> str:
    """把厂商字段归一化为内部 key (auto/huawei/h3c/ruijie)

    兼容: 中文标签、缩写、大小写、空值。无法识别时返回 'auto'。
    """
    if not vendor:
        return "auto"
    key = str(vendor).strip().lower()
    # 精确匹配别名
    if key in _VENDOR_ALIASES:
        return _VENDOR_ALIASES[key]
    # 去掉括号内容再试一次 (如 "华为 (Huawei)" -> "华为")
    bare = key.split("(")[0].strip()
    if bare in _VENDOR_ALIASES:
        return _VENDOR_ALIASES[bare]
    # 原始大小写再试 (如 "华为" 不受 lower 影响, 但 "H3C" -> "h3c" 已匹配)
    orig = str(vendor).strip()
    if orig in _VENDOR_ALIASES:
        return _VENDOR_ALIASES[orig]
    # 含关键字模糊匹配
    if "华为" in orig or "huawei" in key:
        return "huawei"
    if "华三" in orig or "h3c" in key or "comware" in key:
        return "h3c"
    if "锐捷" in orig or "ruijie" in key:
        return "ruijie"
    if "自动" in orig or "auto" in key:
        return "auto"
    return "auto"


@dataclass
class Device:
    """单台交换机设备"""
    name: str = ""                # 用户填写的设备标识(可空, 备份时用实际主机名替换)
    host: str = ""                # IP 地址
    port: int = 22                # 端口
    vendor: str = "auto"         # 厂商: auto / huawei / h3c / ruijie
    protocol: str = "ssh"         # 协议: ssh / telnet
    username: str = ""            # 登录用户名
    password: str = ""            # 登录密码
    enable_password: str = ""     # 特权密码(部分设备需要)
    group: str = "默认"           # 设备分组
    timeout: int = 30             # 连接超时(秒)

    # 运行时状态(不参与连接, 仅展示)
    status: str = "未备份"        # 未备份/备份中/成功/失败
    message: str = ""             # 状态详情
    last_time: str = ""           # 最后备份时间
    last_file: str = ""           # 最后备份文件路径
    real_hostname: str = ""       # 从设备实际获取到的主机名

    def __post_init__(self):
        # 创建/从 JSON 加载时立即归一化 vendor, 防止中文标签等脏值流入
        self.vendor = normalize_vendor(self.vendor)
        if not self.protocol:
            self.protocol = "ssh"

    def device_type(self) -> str:
        """返回 netmiko 使用的 device_type"""
        v = VENDOR_TYPES.get(normalize_vendor(self.vendor))
        if not v:
            raise ValueError(f"不支持的厂商: {self.vendor}")
        key = "telnet" if self.protocol.lower() == "telnet" else "ssh"
        return v[key]

    def vendor_info(self) -> dict:
        return VENDOR_TYPES[self.vendor.lower()]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Device":
        valid = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in valid})


def save_devices_json(devices: list, path: str):
    """把设备列表存为 JSON (密码明文, 仅本地使用)"""
    with open(path, "w", encoding="utf-8") as f:
        json.dump([d.to_dict() for d in devices], f, ensure_ascii=False, indent=2)


def load_devices_json(path: str) -> list:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [Device.from_dict(d) for d in data]
