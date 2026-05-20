from app.github.auth import get_installation_token

INSTALLATION_ID = 133948028

token = get_installation_token(INSTALLATION_ID)

print(token)