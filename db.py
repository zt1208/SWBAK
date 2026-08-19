# -*- coding: utf-8 -*-
"""
db.py
SQLite 数据层 - 设备 / 备份历史 / 应用设置 持久化
替代原 JSON 文件存储, 支持多用户并发安全访问
"""
import json
import os
import sqlite3
import threading
from contextlib import contextmanager

from device import Device

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "swbak.db")

# 全局写锁 (SQLite 写串行, 加锁避免 "database is locked")
_write_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # WAL 提升并发读写
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_conn():
    """获取连接的上下文管理器, 自动关闭"""
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """初始化数据库表"""
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS devices (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT    DEFAULT '',
            host            TEXT    NOT NULL,
            port            INTEGER DEFAULT 22,
            vendor          TEXT    DEFAULT 'auto',
            protocol        TEXT    DEFAULT 'ssh',
            username        TEXT    DEFAULT '',
            password        TEXT    DEFAULT '',
            enable_password TEXT    DEFAULT '',
            grp             TEXT    DEFAULT '默认',
            timeout         INTEGER DEFAULT 30,
            status          TEXT    DEFAULT '未备份',
            message         TEXT    DEFAULT '',
            last_time       TEXT    DEFAULT '',
            last_file       TEXT    DEFAULT '',
            real_hostname   TEXT    DEFAULT '',
            created_at      TEXT    DEFAULT (datetime('now','localtime')),
            UNIQUE(host)
        );

        CREATE TABLE IF NOT EXISTS backups (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            device_host TEXT,
            hostname    TEXT,
            grp         TEXT,
            filepath    TEXT,
            filename    TEXT,
            backup_time TEXT,
            size_chars  INTEGER DEFAULT 0,
            vendor      TEXT,
            status      TEXT,
            message     TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_backups_host ON backups(device_host);
        CREATE INDEX IF NOT EXISTS idx_backups_time ON backups(backup_time);

        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
        """)


# ====================== 设备 CRUD ======================
def _row_to_device(row: sqlite3.Row) -> Device:
    """DB 行 -> Device 对象 (附带 id 动态属性)"""
    d = Device(
        name=row["name"] or "",
        host=row["host"],
        port=int(row["port"]),
        vendor=row["vendor"] or "auto",
        protocol=row["protocol"] or "ssh",
        username=row["username"] or "",
        password=row["password"] or "",
        enable_password=row["enable_password"] or "",
        group=row["grp"] or "默认",
        timeout=int(row["timeout"]),
        status=row["status"] or "未备份",
        message=row["message"] or "",
        last_time=row["last_time"] or "",
        last_file=row["last_file"] or "",
        real_hostname=row["real_hostname"] or "",
    )
    d.id = int(row["id"])
    return d


def list_devices() -> list:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM devices ORDER BY id").fetchall()
    return [_row_to_device(r) for r in rows]


def get_device(device_id: int) -> Device:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM devices WHERE id=?", (device_id,)).fetchone()
    return _row_to_device(row) if row else None


def add_device(d: Device) -> int:
    """新增设备, 返回 id; host 重复则抛异常"""
    with _write_lock, get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO devices
               (name,host,port,vendor,protocol,username,password,enable_password,
                grp,timeout,status,message,last_time,last_file,real_hostname)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (d.name, d.host, int(d.port), d.vendor, d.protocol,
             d.username, d.password, d.enable_password,
             d.group, int(d.timeout),
             d.status, d.message, d.last_time, d.last_file, d.real_hostname),
        )
        return cur.lastrowid


def merge_devices(devices: list) -> dict:
    """批量合并设备 (按 host 去重), 返回 {added, skipped, total}"""
    added, skipped = 0, 0
    with _write_lock, get_conn() as conn:
        existing = {r["host"] for r in conn.execute("SELECT host FROM devices").fetchall()}
        for d in devices:
            if not d.host:
                continue
            if d.host in existing:
                skipped += 1
                continue
            conn.execute(
                """INSERT INTO devices
                   (name,host,port,vendor,protocol,username,password,enable_password,
                    grp,timeout,status,message,last_time,last_file,real_hostname)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (d.name, d.host, int(d.port), d.vendor, d.protocol,
                 d.username, d.password, d.enable_password,
                 d.group, int(d.timeout),
                 "未备份", "", "", "", ""),
            )
            existing.add(d.host)
            added += 1
        total = conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
    return {"added": added, "skipped": skipped, "total": total}


def update_device(device_id: int, d: Device):
    with _write_lock, get_conn() as conn:
        conn.execute(
            """UPDATE devices SET
               name=?,host=?,port=?,vendor=?,protocol=?,username=?,password=?,
               enable_password=?,grp=?,timeout=?
               WHERE id=?""",
            (d.name, d.host, int(d.port), d.vendor, d.protocol,
             d.username, d.password, d.enable_password,
             d.group, int(d.timeout), device_id),
        )


def delete_device(device_id: int):
    with _write_lock, get_conn() as conn:
        conn.execute("DELETE FROM devices WHERE id=?", (device_id,))


def clear_devices():
    with _write_lock, get_conn() as conn:
        conn.execute("DELETE FROM devices")


def update_device_status(device_id: int, status: str, message: str = "",
                         last_time: str = "", last_file: str = "",
                         real_hostname: str = "", vendor: str = ""):
    """备份过程中实时更新设备状态"""
    with _write_lock, get_conn() as conn:
        conn.execute(
            """UPDATE devices SET status=?, message=?, last_time=?, last_file=?,
               real_hostname=COALESCE(NULLIF(?, ''), real_hostname),
               vendor=CASE WHEN ?<>'' THEN ? ELSE vendor END
               WHERE id=?""",
            (status, message, last_time, last_file,
             real_hostname, vendor, vendor, device_id),
        )


# ====================== 备份历史 ======================
def add_backup(device_host: str, hostname: str, group: str, filepath: str,
               filename: str, backup_time: str, size_chars: int,
               vendor: str, status: str, message: str):
    with _write_lock, get_conn() as conn:
        conn.execute(
            """INSERT INTO backups
               (device_host,hostname,grp,filepath,filename,backup_time,
                size_chars,vendor,status,message)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (device_host, hostname, group, filepath, filename, backup_time,
             int(size_chars), vendor, status, message),
        )


def list_backup_history(limit: int = 500, host: str = "") -> list:
    with get_conn() as conn:
        if host:
            rows = conn.execute(
                "SELECT * FROM backups WHERE device_host=? ORDER BY backup_time DESC LIMIT ?",
                (host, limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM backups ORDER BY backup_time DESC LIMIT ?",
                (limit,)).fetchall()
    return [dict(r) for r in rows]


# ====================== 应用设置 (KV) ======================
def get_all_settings() -> dict:
    with get_conn() as conn:
        rows = conn.execute("SELECT key,value FROM settings").fetchall()
    out = {}
    for r in rows:
        try:
            out[r["key"]] = json.loads(r["value"])
        except (json.JSONDecodeError, TypeError):
            out[r["key"]] = r["value"]
    return out


def get_setting(key: str, default=None):
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    if not row:
        return default
    try:
        return json.loads(row["value"])
    except (json.JSONDecodeError, TypeError):
        return row["value"]


def set_setting(key: str, value):
    v = json.dumps(value, ensure_ascii=False)
    with _write_lock, get_conn() as conn:
        conn.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, v),
        )


def update_settings(data: dict):
    with _write_lock, get_conn() as conn:
        for k, v in data.items():
            conn.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (k, json.dumps(v, ensure_ascii=False)),
            )
