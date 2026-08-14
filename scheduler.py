# -*- coding: utf-8 -*-
"""
scheduler.py
定时备份调度器 - 后台线程按间隔/定时自动执行备份任务
支持: 每隔 N 小时 / 每天 N 点 两种模式
"""
import threading
import time
from datetime import datetime


class BackupScheduler:
    """后台定时备份

    mode: "interval" -> 每 interval_hours 小时执行一次
          "daily"    -> 每天 daily_hour 点执行
    task_fn: 回调, 调用时执行实际备份 (无参)
    """

    def __init__(self, task_fn, mode="interval", interval_hours=24,
                 daily_hour=2, on_log=None):
        self.task_fn = task_fn
        self.mode = mode
        self.interval_hours = max(1, int(interval_hours))
        self.daily_hour = int(daily_hour)
        self.on_log = on_log
        self._thread = None
        self._stop = threading.Event()
        self._next_run = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self._log("定时备份已启动")

    def stop(self):
        self._stop.set()
        self._log("定时备份已停止")

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def next_run_str(self) -> str:
        return self._next_run.strftime("%Y-%m-%d %H:%M:%S") if self._next_run else "未计划"

    def _loop(self):
        while not self._stop.is_set():
            now = datetime.now()
            if self.mode == "daily":
                # 今天 daily_hour 点之后, 排到明天
                target = now.replace(hour=self.daily_hour, minute=0, second=0, microsecond=0)
                if now >= target:
                    target = target.replace(day=target.day + 1) if target.day < 28 else \
                        self._add_day(target)
            else:
                target = now.replace(microsecond=0)
                # 立即按间隔推算
                target = self._add_hours(now, self.interval_hours)

            self._next_run = target
            # 等到目标时间 (每 30s 检查一次 stop)
            while not self._stop.is_set() and datetime.now() < target:
                if self._stop.wait(30):
                    return

            if self._stop.is_set():
                return

            self._log(f"开始执行定时备份任务 ({datetime.now():%Y-%m-%d %H:%M:%S})")
            try:
                self.task_fn()
            except Exception as e:
                self._log(f"定时备份异常: {e}")

    @staticmethod
    def _add_hours(dt, hours):
        from datetime import timedelta
        return dt + timedelta(hours=hours)

    @staticmethod
    def _add_day(dt):
        from datetime import timedelta
        return dt + timedelta(days=1)

    def _log(self, msg):
        if self.on_log:
            try:
                self.on_log(msg)
            except Exception:
                pass
