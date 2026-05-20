from fastapi import FastAPI, Request

from app.github.webhooks import verify_github_signature

app = FastAPI()


@app.get("/")
def root():
    return {"status": "RepoHeal running"}


@app.post("/webhook/github")
async def github_webhook(request: Request):

    await verify_github_signature(request)

    payload = await request.json()

    event_type = request.headers.get("X-GitHub-Event")

    print(f"[INFO] Received GitHub event: {event_type}")

    return {
        "received": True,
        "event": event_type
    }