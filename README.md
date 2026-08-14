# SWBAK - 交换机配置备份工具

> 基于 Python 的网络设备配置备份工具，支持华为 / 华三 / 锐捷交换机，通过 SSH/Telnet 多线程批量备份运行配置。

## 功能特性

- **多厂商支持** — 华为 (Huawei)、华三 (H3C)、锐捷 (Ruijie)，自动识别无需手动选择
- **多线程并发** — ThreadPoolExecutor 并行备份，1000 台设备高效完成
- **批量导入** — 支持 Excel / CSV / TXT 文件导入，粘贴录入，统一密码导入
- **自动识别厂商** — 登录后通过提示符 + Version 命令智能判断设备类型
- **配置版本对比** — 同设备两次备份差异一目了然（unified diff）
- **全文搜索** — 跨所有备份配置搜索关键字
- **定时备份** — 间隔模式 / 定时模式，后台自动执行
- **邮件通知** — 备份完成自动发送 HTML 结果报告
- **自动导出报告** — 每次备份后生成 Excel 报告，成功/失败设备分 Sheet 展示
- **凭据持久化** — 账号密码本地保存，重启不丢失，自动填充
- **只读操作** — 仅执行 display/show 命令，不修改设备任何配置

## 快速部署

### 方式一：一键启动（推荐）

```bash
# 1. 克隆仓库
git clone https://github.com/你的用户名/SWBAK.git
cd SWBAK

# 2. 双击 start.bat（自动检查 Python + 安装依赖 + 启动程序）
```

> Windows 用户直接双击 `start.bat` 即可，脚本会自动完成环境检查、依赖安装和程序启动。

### 方式二：手动部署

```bash
# 1. 克隆仓库
git clone https://github.com/你的用户名/SWBAK.git
cd SWBAK

# 2. 安装依赖
pip install -r requirements.txt

# 3. 运行
python main.py
```

### 环境要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Windows 7/10/11（64位） |
| Python | 3.8 及以上 |
| 网络 | 管理终端需能 SSH/Telnet 访问目标交换机 |

> 安装 Python 时请勾选 **"Add Python to PATH"**。下载地址：https://www.python.org/downloads/

### 依赖列表

| 库名 | 用途 |
|------|------|
| netmiko >= 4.2.0 | SSH/Telnet 多厂商交换机连接 |
| openpyxl >= 3.1.2 | Excel 批量导入读取 |
| xlsxwriter >= 3.1.2 | Excel 报告导出 |

## 使用指南

### 1. 添加设备

点击工具栏 **"添加设备"**，支持 4 种方式：

| 方式 | 说明 | 适用场景 |
|------|------|----------|
| 手动添加 | 逐台填写 IP、账号、密码等 | 少量设备 |
| 批量录入 | 粘贴多行 `IP 用户名 密码` | 中等规模，设备密码不同 |
| 统一密码导入 | 粘贴 IP 列表，统一输入一组密码 | 大规模，设备密码统一 |
| 从文件导入 | Excel/CSV/TXT 文件导入 | 已有设备清单台账 |

> 厂商选择 **"自动识别"** 即可，工具会在登录后自动判断。

### 2. 执行备份

点击工具栏 **"开始备份"**，程序自动完成：

1. 多线程并发连接所有设备
2. 自动识别厂商类型
3. 抓取运行配置
4. 按分组 / 设备主机名保存配置文件
5. 自动导出 Excel 报告（成功/失败分两个 Sheet）

### 3. 查看结果

- **设备列表** — 备份完成后自动按状态（成功/失败）和 IP 地址排序
- **日志区** — 实时显示连接过程、厂商识别、配置输出摘要
- **Excel 报告** — 自动导出到 `reports/` 目录

### 4. 其他功能

| 功能 | 入口 | 说明 |
|------|------|------|
| 配置对比 | 工具 → 配置对比 | 对比同设备两次备份的差异 |
| 配置搜索 | 工具 → 配置搜索 | 跨所有备份文件搜索关键字 |
| 定时备份 | 设置 → 定时备份 | 间隔模式 / 每天 N 点自动备份 |
| 邮件通知 | 设置 → 邮件通知 | 备份完成自动发送结果邮件 |
| 导出模板 | 文件 → 导出导入模板 | 生成标准批量导入模板 |

## 配置文件保存结构

```
backups/
  └── 核心机房/                              ← 分组文件夹
      ├── Core-SW-01/                        ← 设备实际主机名
      │   ├── Core-SW-01_20260813_103650.txt   ← 带时间戳的备份
      │   └── latest.txt                       ← 最新备份（方便对比）
      └── Core-SW-02/
          ├── Core-SW-02_20260813_103650.txt
          └── latest.txt
  └── 接入层/
      └── Access-SW-01/
          ├── Access-SW-01_20260813_103650.txt
          └── latest.txt

reports/
  └── backup_report_20260813_103650.xlsx     ← 自动导出的报告
```

## 项目结构

```
SWBAK/
├── main.py              # 主程序入口 (GUI 界面)
├── backup_engine.py     # 备份引擎 (SSH/Telnet 连接、厂商识别、配置抓取)
├── device.py            # 设备数据模型与厂商命令定义
├── importer.py          # 批量导入模块 (Excel/CSV/TXT 解析)
├── gui_dialogs.py       # GUI 对话框 (添加设备、批量导入、配置对比等)
├── config_compare.py    # 配置对比与全文搜索
├── notifier.py          # 邮件通知模块
├── scheduler.py         # 定时备份调度器
├── app_config.py        # 应用配置管理 (JSON 持久化)
├── requirements.txt     # Python 依赖列表
├── start.bat            # 一键启动脚本
└── 使用说明.md           # 详细使用说明文档
```

## 支持的交换机厂商

| 厂商 | 配置命令 | 关闭分页命令 | 协议 |
|------|----------|-------------|------|
| 华为 (Huawei) | `display current-configuration` | `screen-length 0 temporary` | SSH / Telnet |
| 华三 (H3C) | `display current-configuration` | `screen-length disable` | SSH / Telnet |
| 锐捷 (Ruijie) | `show running-config` | `terminal length 0` | SSH / Telnet |

## 批量导入文件格式

支持 Excel(.xlsx/.xls)、CSV、TXT，表头兼容中英文，列顺序不限：

| 设备名称 | IP地址 | 端口 | 厂商 | 协议 | 用户名 | 密码 | 特权密码 | 分组 |
|----------|--------|------|------|------|--------|------|----------|------|
| 核心-01 | 10.0.0.1 | 22 | auto | ssh | admin | Admin@123 | | 核心机房 |
| 接入-02 | 10.0.0.2 | 22 | huawei | ssh | admin | Admin@123 | | 接入层 |
| 接入-03 | 10.0.0.3 | 23 | ruijie | telnet | admin | Admin@123 | Admin@enable | 接入层 |

> 厂商列填 `auto` 自动识别，或填 `huawei` / `h3c` / `ruijie` 手动指定。

## 常见问题

<details>
<summary><b>双击 start.bat 打不开？</b></summary>

- 确认已安装 Python 3.8+，安装时勾选了 "Add Python to PATH"
- 在命令行手动执行 `python main.py` 查看报错
</details>

<details>
<summary><b>批量导入识别不到 IP 地址？</b></summary>

- 确保表头包含 IP 相关字段（如 "IP地址"、"IP"、"管理IP"、"host"）
- 工具会自动回退扫描数据列，通过 IP 正则匹配识别
</details>

<details>
<summary><b>登录成功但无法识别厂商？</b></summary>

- 工具依次尝试：提示符判断 → Version 命令 → 逐厂商登录
- 如均失败，检查设备是否修改了默认提示符
- 可在添加设备时手动指定厂商类型
</details>

<details>
<summary><b>备份速度慢？</b></summary>

- 设置中调整并发线程数（建议 10-20）
- 厂商自动识别已优化为提示符优先（约 0.5 秒）
- 网络延迟高的设备可适当增加连接超时
</details>

<details>
<summary><b>批量备份 1000 台会影响设备吗？</b></summary>

- **不会**。工具只执行只读命令（display/show），不修改或保存配置
- 每台设备仅建立 1 个连接，执行查询后立即断开
- 建议线程数不超过 20，避开业务高峰期
</details>

<details>
<summary><b>密码会丢失吗？</b></summary>

- 不会。账号密码保存在 `config.json` 和 `devices.json` 中
- 重启程序后自动加载，添加新设备时自动填充
</details>

## 技术架构

### 厂商自动识别流程

```
登录设备 (autodetect 连接)
    │
    ├─ ① 提示符判断 (find_prompt, ~0.5s)
    │     锐捷: hostname> 或 hostname# → ruijie
    │
    ├─ ② Version 命令判断 (send_command_timing, ~3s)
    │     发送 display version / show version
    │     输出含 "Huawei" → huawei
    │     输出含 "H3C"/"Comware" → h3c
    │     输出含 "Ruijie" → ruijie
    │
    └─ ③ 逐厂商回退 (每种 15s 超时)
          依次用 huawei / h3c / ruijie 方式登录确认
```

### 多线程备份

使用 `ThreadPoolExecutor` 实现并发备份，每台设备在独立线程中执行连接、识别、抓取、保存，线程数可配置（默认 10），备份进度实时更新到 UI。

### 数据安全

- 工具仅执行只读命令，**不修改设备配置**
- 密码本地存储（明文 JSON），仅限本机使用
- 配置文件保存在本地，不上传任何远程服务器

## 许可证

本项目仅供学习和内部使用。

## 相关文档

详细使用说明请参考 [使用说明.md](使用说明.md)。
