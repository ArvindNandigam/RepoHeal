from __future__ import annotations

import logging
import smtplib
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


def send_email(
    host: str,
    port: int,
    user: str,
    password: str,
    from_addr: str,
    to_addr: str,
    subject: str,
    body: str,
) -> bool:
    if not all([host, user, password, from_addr, to_addr]):
        logger.warning("Email not configured — skipping send")
        return False
    msg = MIMEText(body, _charset="utf-8")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    try:
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.starttls()
            server.login(user, password)
            server.send_message(msg)
        logger.info("Email sent to %s: %s", to_addr, subject)
        return True
    except Exception as e:
        logger.error("Failed to send email: %s", e)
        return False
