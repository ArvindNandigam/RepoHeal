from fastapi import FastAPI

app = FastAPI()


@app.get("/")
def root():
    return {"status": "RepoHeal running"}


@app.post("/webhook/github")
async def github_webhook():
    return {"received": True}