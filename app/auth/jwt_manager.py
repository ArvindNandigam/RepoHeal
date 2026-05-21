from datetime import (
    datetime,
    timedelta
)

import jwt

from fastapi import (
    HTTPException,
    Request
)

from app.config import settings

JWT_SECRET = settings.JWT_SECRET_KEY

JWT_ALGORITHM = "HS256"


def create_session_token(
    payload: dict
):

    payload["exp"] = (
        datetime.utcnow()
        + timedelta(days=1)
    )

    return jwt.encode(
        payload,
        JWT_SECRET,
        algorithm=JWT_ALGORITHM
    )


def verify_session_token(
    request: Request
):

    token = request.cookies.get(
        "repoheal_session"
    )

    if not token:

        raise HTTPException(
            status_code=401,
            detail="Authentication required"
        )

    try:

        decoded = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM]
        )

        return decoded

    except jwt.PyJWTError:

        raise HTTPException(
            status_code=401,
            detail="Invalid session"
        )