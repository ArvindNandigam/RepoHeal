import time

import jwt
import requests

from app.config import settings


GITHUB_APP_ID = settings.GITHUB_APP_ID
PRIVATE_KEY = settings.GITHUB_PRIVATE_KEY


def generate_jwt():

    payload = {
        "iat": int(time.time()),
        "exp": int(time.time()) + 600,
        "iss": GITHUB_APP_ID,
    }

    encoded_jwt = jwt.encode(
        payload,
        PRIVATE_KEY,
        algorithm="RS256"
    )

    return encoded_jwt


def get_installation_token(installation_id):

    jwt_token = generate_jwt()

    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "Accept": "application/vnd.github+json",
    }

    url = (
        "https://api.github.com/app/installations/"
        f"{installation_id}/access_tokens"
    )

    response = requests.post(url, headers=headers)

    response.raise_for_status()

    return response.json()["token"]