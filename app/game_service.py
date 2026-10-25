"""Правила розыгрыша: три предложения, одна активная игра, личная история."""

from datetime import datetime, timezone
import logging
import random

from fastapi import HTTPException

logger = logging.getLogger("game_roll")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def next_id(items):
    return max((item["id"] for item in items), default=0) + 1


def find(items, item_id, label):
    for item in items:
        if item["id"] == item_id:
            return item
    raise HTTPException(status_code=404, detail=f"{label} не найден")


def active_assignment(data, player_id):
    return next(
        (item for item in data["assignments"] if item["player_id"] == player_id and item["status"] == "playing"),
        None,
    )


def pending_round(data, player_id):
    return next(
        (item for item in data["rounds"] if item["player_id"] == player_id and not item["accepted"]),
        None,
    )


def accept(data, round_):
    # Повторный запрос не создаёт вторую запись в таблице.
    if round_["accepted"]:
        return next(item for item in data["assignments"] if item["round_id"] == round_["id"])
    assignment = {
        "id": next_id(data["assignments"]), "round_id": round_["id"],
        "player_id": round_["player_id"], "game": round_["game"],
        "status": "playing", "spent_hours": None, "comment": "",
        "created_at": now(), "updated_at": now(),
    }
    data["assignments"].append(assignment)
    round_["accepted"] = True
    logger.info("Game accepted: player=%s game=%s", round_["player_id"], round_["game"]["id"])
    return assignment


def draw(data, player, round_, games):
    candidates = [game for game in games
        if game["id"] not in player["seen_game_ids"]
        and (round_["max_hours"] is None or game["hours"] <= round_["max_hours"])]
    if not candidates:
        raise HTTPException(status_code=409, detail="Подходящих новых игр нет. Измени ограничение времени.")
    round_["game"] = random.choice(candidates)
    round_["attempt"] += 1
    player["seen_game_ids"].append(round_["game"]["id"])
    logger.info("Game offered: player=%s attempt=%s game=%s", player["id"], round_["attempt"], round_["game"]["id"])
    if round_["attempt"] == 3:
        accept(data, round_)
    return round_
