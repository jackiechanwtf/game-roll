"""Game Roll: небольшой FastAPI-сервис для выбора игры."""

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Query

load_dotenv()

VERSION = "1.0.0"
BASE_DIR = Path(__file__).resolve().parent
GAMES = json.loads((BASE_DIR / "catalogue.json").read_text(encoding="utf-8"))
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


@app.get("/games")
def list_games(max_hours: float | None = Query(default=None, gt=0, le=1000)):
    return [game for game in GAMES if max_hours is None or game["hours"] <= max_hours]
