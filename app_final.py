"""FastAPI-маршруты Game Roll. Запуск: python -m uvicorn app_final:app."""

from contextlib import asynccontextmanager
from hashlib import sha256
import json
import logging
import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from game_service import accept, active_assignment, draw, find, next_id, now, pending_round
from storage import JsonStorage

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
VERSION = "1.0.0"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("game_roll")


class PlayerInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=40)


class RollInput(BaseModel):
    player_id: int = Field(gt=0)
    max_hours: float | None = Field(default=None, gt=0, le=1000, allow_inf_nan=False)


class FinishInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    status: Literal["completed", "dropped"]
    spent_hours: float = Field(ge=0, le=10000, allow_inf_nan=False)
    comment: str = Field(default="", max_length=500)


class ChoiceInput(BaseModel):
    attempt: int = Field(ge=1, le=3)


def create_app(data_file=None, games=None):
    """Отдельный файл и маленький каталог позволяют изолировать каждый тест."""

    @asynccontextmanager
    async def lifespan(app):
        path = Path(data_file or os.getenv("GAME_ROLL_DATA", "data/state.json"))
        if not path.is_absolute():
            path = BASE_DIR / path
        app.state.storage = JsonStorage(path)
        catalogue_path = Path(os.getenv("GAMES_FILE", "catalogue.json"))
        if not catalogue_path.is_absolute():
            catalogue_path = BASE_DIR / catalogue_path
        app.state.games = games if games is not None else json.loads(
            catalogue_path.read_text(encoding="utf-8")
        )
        logger.info("Service started: name=%s games=%s data=%s", app.title, len(app.state.games), path)
        yield
        logger.info("Service stopped")

    app = FastAPI(title="Game Roll", version=VERSION, lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

    @app.middleware("http")
    async def request_log(request, call_next):
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
        logger.info("%s %s status=%s", request.method, request.url.path, response.status_code)
        return response

    @app.get("/")
    def home():
        page = (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")
        # При изменении файла меняется ссылка, и браузер загружает новую версию.
        for name in ("style.css", "app.js"):
            version = sha256((BASE_DIR / "static" / name).read_bytes()).hexdigest()[:12]
            page = page.replace(f"/static/{name}", f"/static/{name}?v={version}")
        return HTMLResponse(page)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/version")
    def version():
        return {"version": VERSION}

    @app.get("/games")
    def list_games(max_hours: float | None = Query(default=None, gt=0, le=1000, allow_inf_nan=False)):
        return [game for game in app.state.games if max_hours is None or game["hours"] <= max_hours]

    @app.get("/players")
    def list_players():
        return [{"id": player["id"], "name": player["name"]} for player in app.state.storage.read()["players"]]

    @app.post("/players")
    def enter_player(body: PlayerInput):
        with app.state.storage.transaction() as data:
            for player in data["players"]:
                if player["name"].casefold() == body.name.casefold():
                    return {"id": player["id"], "name": player["name"]}
            player = {"id": next_id(data["players"]), "name": body.name, "seen_game_ids": []}
            data["players"].append(player)
            logger.info("Player created: id=%s", player["id"])
            return {"id": player["id"], "name": player["name"]}

    @app.get("/players/{player_id}/state")
    def player_state(player_id: int):
        data = app.state.storage.read()
        player = find(data["players"], player_id, "Игрок")
        return {"player": {"id": player["id"], "name": player["name"]},
                "round": pending_round(data, player_id),
                "assignment": active_assignment(data, player_id)}

    @app.post("/rolls", status_code=201)
    def start_round(body: RollInput):
        with app.state.storage.transaction() as data:
            player = find(data["players"], body.player_id, "Игрок")
            if active_assignment(data, player["id"]):
                raise HTTPException(status_code=409, detail="Сначала отметь текущую игру пройденной или брошенной.")
            if pending_round(data, player["id"]):
                raise HTTPException(status_code=409, detail="У тебя уже есть незавершённый выбор.")
            candidates = [game for game in app.state.games if game["id"] not in player["seen_game_ids"] and (body.max_hours is None or game["hours"] <= body.max_hours)]
            if len(candidates) < 3:
                raise HTTPException(status_code=409, detail="Для трёх попыток нужно хотя бы 3 новые игры. Увеличь лимит часов.")
            round_ = {"id": next_id(data["rounds"]), "player_id": player["id"], "attempt": 0, "accepted": False, "max_hours": body.max_hours}
            data["rounds"].append(round_)
            return draw(data, player, round_, app.state.games)

    @app.post("/rolls/{round_id}/reroll")
    def reroll(round_id: int, body: ChoiceInput):
        with app.state.storage.transaction() as data:
            round_ = find(data["rounds"], round_id, "Розыгрыш")
            if round_["accepted"]:
                raise HTTPException(status_code=409, detail="Игра уже принята. Переброс недоступен.")
            if body.attempt != round_["attempt"]:
                raise HTTPException(status_code=409, detail="Попытка уже изменилась в другой вкладке. Данные обновлены.")
            player = find(data["players"], round_["player_id"], "Игрок")
            return draw(data, player, round_, app.state.games)

    @app.post("/rolls/{round_id}/accept")
    def accept_game(round_id: int, body: ChoiceInput):
        with app.state.storage.transaction() as data:
            round_ = find(data["rounds"], round_id, "Розыгрыш")
            if body.attempt != round_["attempt"]:
                raise HTTPException(status_code=409, detail="Попытка уже изменилась в другой вкладке. Данные обновлены.")
            return accept(data, round_)

    @app.get("/assignments")
    def list_assignments():
        data = app.state.storage.read()
        names = {player["id"]: player["name"] for player in data["players"]}
        return [{**item, "player_name": names[item["player_id"]]} for item in reversed(data["assignments"])]

    @app.patch("/assignments/{assignment_id}")
    def finish_game(assignment_id: int, body: FinishInput):
        with app.state.storage.transaction() as data:
            item = find(data["assignments"], assignment_id, "Запись")
            if item["status"] != "playing":
                raise HTTPException(status_code=409, detail="Эта игра уже завершена.")
            item.update(status=body.status, spent_hours=body.spent_hours,
                        comment=body.comment, updated_at=now())
            logger.info("Game finished: player=%s game=%s status=%s", item["player_id"], item["game"]["id"], item["status"])
            return item

    return app


app = create_app()
