from __future__ import annotations

import logging
import httpx
from app.config import get_settings

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
    settings = get_settings()
    api_key = settings.resend_api_key
    
    if not from_addr or not to_addr or not api_key:
        logger.warning("Email not configured (RESEND_API_KEY missing) — skipping send")
        return False
        
    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "from": from_addr,
            "to": [to_addr],
            "subject": subject,
            "text": body
        }

        # Use httpx to send a POST request to Resend API
        response = httpx.post(
            "https://api.resend.com/emails",
            headers=headers,
            json=payload,
            timeout=10.0
        )

        if response.status_code in (200, 201):
            logger.info("Email sent to %s: %s", to_addr, subject)
            return True
        else:
            logger.error("Failed to send email. Resend API returned %s: %s", response.status_code, response.text)
            return False
            
    except Exception as e:
        logger.error("Failed to send email: %s", e)
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
