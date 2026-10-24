"""Game Roll: небольшой FastAPI-сервис для выбора игры."""

import os

from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()

VERSION = "1.0.0"
app = FastAPI(title=os.getenv("APP_NAME", "Game Roll"), version=VERSION)


@app.get("/")
def home():
    return {"message": "Game Roll работает", "docs": "/docs"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/version")
def version():
    return {"version": VERSION}
