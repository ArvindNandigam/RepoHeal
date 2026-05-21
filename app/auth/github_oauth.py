import requests

from fastapi import (
    APIRouter,
    HTTPException,
    Request,
    Response
)
import secrets
from app.auth.session_store import (
    session_store
)
from fastapi.responses import (
    RedirectResponse
)

from app.auth.jwt_manager import (
    create_session_token
)

from app.config import settings

from app.utils.logger import (
    get_logger
)

logger = get_logger(__name__)

router = APIRouter()


GITHUB_CLIENT_ID = (
    settings.GITHUB_OAUTH_CLIENT_ID
)

GITHUB_CLIENT_SECRET = (
    settings.GITHUB_OAUTH_CLIENT_SECRET
)

BASE_URL = (
    "https://repoheal.onrender.com"
)

STATE_COOKIE_NAME = "repoheal_oauth_state"


@router.get("/login")
async def github_login():

    state = secrets.token_hex(16)

    github_auth_url = (
        "https://github.com/login/oauth/authorize"
        f"?client_id={GITHUB_CLIENT_ID}"
        "&scope=repo read:user"
        f"&state={state}"
    )

    redirect = RedirectResponse(
        github_auth_url
    )
    redirect.set_cookie(
        key=STATE_COOKIE_NAME,
        value=state,
        httponly=True,
        secure=(
            settings.ENVIRONMENT == "production"
        ),
        samesite="lax",
        max_age=300
    )

    return redirect


@router.get("/callback")
async def github_callback(
    code: str,
    state: str,
    request: Request,
    response: Response
):

    cookie_state = request.cookies.get(
        STATE_COOKIE_NAME
    )

    if not cookie_state or cookie_state != state:

        raise HTTPException(
            status_code=401,
            detail="Invalid OAuth state"
        )

    token_response = requests.post(
        "https://github.com/login/oauth/access_token",
        headers={
            "Accept": "application/json"
        },
        data={
            "client_id": (
                GITHUB_CLIENT_ID
            ),
            "client_secret": (
                GITHUB_CLIENT_SECRET
            ),
            "code": code
        },
        timeout=15
    )

    if token_response.status_code != 200:

        raise HTTPException(
            status_code=401,
            detail="GitHub OAuth failed"
        )

    token_data = token_response.json()

    access_token = token_data.get(
        "access_token"
    )

    if not access_token:

        raise HTTPException(
            status_code=401,
            detail="GitHub OAuth failed"
        )

    user_response = requests.get(
        "https://api.github.com/user",
        headers={
            "Authorization":
                f"Bearer {access_token}"
        },
        timeout=15
    )

    if user_response.status_code != 200:

        raise HTTPException(
            status_code=401,
            detail="GitHub user lookup failed"
        )

    github_user = user_response.json()

    session_store.delete_sessions_for_github_user(
        github_user["id"]
    )

    session_id = secrets.token_hex(16)

    session_store.create_session(
        session_id=session_id,
        github_id=github_user["id"],
        github_login=github_user["login"],
        github_token=access_token
    )

    jwt_token = create_session_token({
        "github_id": github_user["id"],
        "github_login": github_user["login"],
        "session_id": session_id
    })

    redirect = RedirectResponse(
        url="/dashboard"
    )

    redirect.set_cookie(
        key="repoheal_session",
        value=jwt_token,
        httponly=True,
        secure=(
            settings.ENVIRONMENT == "production"
        ),
        samesite="lax"
        ,
        max_age=86400,
        path="/"
    )

    redirect.delete_cookie(
        STATE_COOKIE_NAME
    )

    logger.info(
        f"GitHub OAuth login success: "
        f"{github_user['login']}"
    )

    return redirect