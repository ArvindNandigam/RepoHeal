from fastapi import FastAPI
from app.errors.exceptions import RepoHealError, repoheal_error_handler

def register_error_handlers(app: FastAPI):
    app.add_exception_handler(RepoHealError, repoheal_error_handler)
