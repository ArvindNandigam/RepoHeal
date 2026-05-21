import hashlib
import hmac

from fastapi import HTTPException, Request
from app.config import settings


GITHUB_WEBHOOK_SECRET = settings.GITHUB_WEBHOOK_SECRET


async def verify_github_signature(request: Request):

    signature_header = request.headers.get("X-Hub-Signature-256")

    if not signature_header:
        raise HTTPException(
            status_code=401,
            detail="Missing GitHub signature header"
        )

    body = await request.body()

    expected_signature = "sha256=" + hmac.new(
        key=GITHUB_WEBHOOK_SECRET.encode(),
        msg=body,
        digestmod=hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, signature_header):
        raise HTTPException(
            status_code=401,
            detail="Invalid GitHub webhook signature"
        )

    return True