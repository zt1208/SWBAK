# -*- coding: utf-8 -*-
"""WSGI 入口 - 服务器生产部署用 (gunicorn)
启动示例:
    venv/bin/gunicorn --workers 1 --threads 16 -b 0.0.0.0:5000 wsgi:app
说明:
    - workers 固定为 1: 备份调度器随应用启动, 多 worker 会导致调度器重复运行
    - threads 承担并发 (含 SSE 长连接), 对内部工具规模足够
"""
from web_app import app  # noqa: F401  (导入即完成 DB 初始化与调度器启动)

if __name__ == "__main__":
    # 本地直跑 (调试用)
    app.run(host="0.0.0.0", port=5000, threaded=True, debug=False)
