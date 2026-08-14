# -*- coding: utf-8 -*-
"""
config_compare.py
配置文件对比 - 对比同一设备两次备份的差异(主流软件标配功能)
"""
import difflib
import os
from datetime import datetime


def list_backups(device_dir: str) -> list:
    """列出某设备目录下所有备份文件 (按时间倒序)"""
    if not os.path.isdir(device_dir):
        return []
    files = []
    for f in os.listdir(device_dir):
        # 支持 .txt 和旧的 .cfg; 排除 latest 占位文件
        is_backup = f.endswith(".txt") or f.endswith(".cfg")
        is_latest = f in ("latest.txt", "latest.cfg")
        if is_backup and not is_latest:
            p = os.path.join(device_dir, f)
            files.append((f, p, os.path.getmtime(p)))
    files.sort(key=lambda x: x[2], reverse=True)
    return files


def read_lines(path: str) -> list:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read().splitlines()


def compare(old_path: str, new_path: str, context: int = 2) -> dict:
    """对比两个配置文件, 返回 {diff_text, added, removed, changed}
    diff_text: 带行号的 unified diff 文本
    """
    old = read_lines(old_path)
    new = read_lines(new_path)

    diff = list(difflib.unified_diff(
        old, new,
        fromfile=os.path.basename(old_path),
        tofile=os.path.basename(new_path),
        lineterm="", n=context
    ))

    added = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))

    # 带行号的 HTML 风格 diff 文本
    diff_text = "\n".join(diff) if diff else "(无差异)"

    return {
        "diff_text": diff_text,
        "added": added,
        "removed": removed,
        "changed": added + removed,
        "is_different": bool(diff),
        "old_mtime": datetime.fromtimestamp(os.path.getmtime(old_path)).strftime("%Y-%m-%d %H:%M:%S"),
        "new_mtime": datetime.fromtimestamp(os.path.getmtime(new_path)).strftime("%Y-%m-%d %H:%M:%S"),
    }


def search_in_configs(backup_dir: str, keyword: str) -> list:
    """在所有备份配置中搜索关键字, 返回 [(file, line_no, line_text)]"""
    results = []
    if not os.path.isdir(backup_dir):
        return results
    for root, _, files in os.walk(backup_dir):
        for f in files:
            # 支持 .txt 和旧的 .cfg
            if not (f.endswith(".txt") or f.endswith(".cfg")):
                continue
            p = os.path.join(root, f)
            try:
                with open(p, "r", encoding="utf-8", errors="ignore") as fp:
                    for i, line in enumerate(fp, 1):
                        if keyword.lower() in line.lower():
                            results.append((p, i, line.rstrip()))
            except Exception:
                continue
    return results
