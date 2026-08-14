# -*- coding: utf-8 -*-
"""
notifier.py
邮件通知 - 备份完成后发送结果汇总(失败/成功统计)
"""
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime


def send_report(smtp_host: str, smtp_port: int, sender: str, password: str,
                recipients: list, subject: str, html_body: str,
                use_ssl: bool = True, timeout: int = 30) -> tuple:
    """发送邮件, 返回 (success, message)"""
    if not recipients:
        return False, "收件人为空"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        if use_ssl:
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=timeout)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=timeout)
            server.starttls()
        if password:
            server.login(sender, password)
        server.sendmail(sender, recipients, msg.as_string())
        server.quit()
        return True, "发送成功"
    except Exception as e:
        return False, str(e)


def build_report_html(title: str, devices: list) -> str:
    """根据设备列表生成 HTML 报告"""
    total = len(devices)
    ok = sum(1 for d in devices if d.status == "成功")
    fail = total - ok
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    rows = ""
    for d in devices:
        color = "#28a745" if d.status == "成功" else "#dc3545"
        rows += (
            f"<tr>"
            f"<td>{d.real_hostname or d.name or d.host}</td>"
            f"<td>{d.host}</td>"
            f"<td>{d.vendor}</td>"
            f"<td style='color:{color};font-weight:bold'>{d.status}</td>"
            f"<td>{d.message}</td>"
            f"<td>{d.last_time}</td>"
            f"</tr>"
        )

    html = f"""
    <html><body style="font-family: Microsoft YaHei, Arial, sans-serif; color:#333;">
      <h2 style="color:#1f6feb;">{title}</h2>
      <p>生成时间: {now}</p>
      <p>总计 <b>{total}</b> 台, 成功 <b style="color:#28a745">{ok}</b> 台,
         失败 <b style="color:#dc3545">{fail}</b> 台</p>
      <table border="1" cellpadding="6" cellspacing="0"
             style="border-collapse:collapse;font-size:13px;">
        <tr style="background:#f0f3f7;">
          <th>设备名</th><th>IP</th><th>厂商</th>
          <th>状态</th><th>详情</th><th>备份时间</th>
        </tr>
        {rows}
      </table>
      <p style="color:#888;font-size:12px;margin-top:16px;">
        本邮件由 交换机配置备份工具 自动发送
      </p>
    </body></html>
    """
    return html
