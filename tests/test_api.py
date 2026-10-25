"""Проверки API и правил выбора. Каждый тест получает отдельный JSON-файл."""

from concurrent.futures import ThreadPoolExecutor
import json
import logging
import re

from fastapi.testclient import TestClient
import pytest

from app.main import create_app


@pytest.fixture
def games():
    return [
        {"id": i, "name": f"Game {i}", "hours": i * 2, "genres": "Adventure", "source_url": f"https://howlongtobeat.com/game/{i}"}
        for i in range(1, 9)
    ]


@pytest.fixture
def client(tmp_path, games, monkeypatch):
    # Результат предсказуем: проверяем правила, а не удачу генератора случайных чисел.
    monkeypatch.setattr("app.game_service.random.choice", lambda candidates: candidates[0])
    with TestClient(create_app(tmp_path / "state.json", games)) as client:
        yield client


def enter(client, name="Тимофей"):
    response = client.post("/players", json={"name": name})
    assert response.status_code == 200
    return response.json()["id"]


def roll(client, player_id, max_hours=None):
    response = client.post("/rolls", json={"player_id": player_id, "max_hours": max_hours})
    assert response.status_code == 201
    return response.json()


def test_health_version_and_web_page(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/version").json() == {"version": "1.0.0"}
    page = client.get("/")
    assert page.status_code == 200
    assert "Кто во что играет" in page.text
    assert client.get("/static/app.js").status_code == 200


def test_catalogue_filter(client):
    games = client.get("/games", params={"max_hours": 6}).json()
    assert [game["id"] for game in games] == [1, 2, 3]
    assert client.get("/games", params={"max_hours": 1}).json() == []


def test_browser_gets_new_asset_url_after_file_changes(tmp_path, games, monkeypatch):
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text('<link href="/static/style.css"><script src="/static/app.js"></script>')
    (static / "style.css").write_text("body { color: green; }")
    (static / "app.js").write_text('console.log("Game Roll");')
    monkeypatch.setattr("app.main.BASE_DIR", tmp_path)
    with TestClient(create_app(tmp_path / "state.json", games)) as client:
        before = client.get("/")
        assert before.headers["cache-control"] == "no-cache"
        old_urls = re.findall(r'/static/[^"?]+\?v=[^" ]+', before.text)
        assert len(old_urls) == 2
        assert client.get(old_urls[0]).headers["cache-control"] == "no-cache"
        (static / "style.css").write_text("body { color: blue; }")
        after = client.get("/")
        new_urls = re.findall(r'/static/[^"?]+\?v=[^" ]+', after.text)
        assert new_urls[0] != old_urls[0]
        assert new_urls[1] == old_urls[1]
        assert client.get(new_urls[0]).text == "body { color: blue; }"


@pytest.mark.parametrize("name", ["", "   ", "x" * 41])
def test_invalid_player_name(client, name):
    assert client.post("/players", json={"name": name}).status_code == 422
    assert client.get("/players").json() == []


def test_same_name_returns_existing_player(client):
    first = enter(client, "  Тимофей  ")
    assert enter(client, "ТИМОФЕЙ") == first
    assert client.get("/players").json() == [{"id": first, "name": "Тимофей"}]


@pytest.mark.parametrize("max_hours", [0, -1, "abc", "nan", "inf"])
def test_invalid_duration(client, max_hours):
    player_id = enter(client)
    assert client.post("/rolls", json={"player_id": player_id, "max_hours": max_hours}).status_code == 422
    assert client.get(f"/players/{player_id}/state").json()["round"] is None


def test_accept_first_game_blocks_next_round(client):
    player_id = enter(client)
    offer = roll(client, player_id)
    response = client.post(f"/rolls/{offer['id']}/accept", json={"attempt": 1})
    assert response.status_code == 200
    assert response.json()["game"] == offer["game"]
    assert response.json()["status"] == "playing"
    assert client.post("/rolls", json={"player_id": player_id}).status_code == 409
    # Повторная отправка формы не добавляет вторую строку в общую таблицу.
    again = client.post(f"/rolls/{offer['id']}/accept", json={"attempt": 1})
    assert again.json()["id"] == response.json()["id"]
    assert len(client.get("/assignments").json()) == 1


def test_third_game_is_accepted_and_fourth_is_unavailable(client):
    player_id = enter(client)
    offer = roll(client, player_id, max_hours=6)
    seen = [offer["game"]["id"]]
    assert client.post("/rolls", json={"player_id": player_id}).status_code == 409
    for attempt in (1, 2):
        response = client.post(f"/rolls/{offer['id']}/reroll", json={"attempt": attempt})
        assert response.status_code == 200
        offer = response.json()
        seen.append(offer["game"]["id"])
    assert len(set(seen)) == 3
    assert offer["attempt"] == 3 and offer["accepted"] is True
    assert client.post(f"/rolls/{offer['id']}/reroll", json={"attempt": 3}).status_code == 409
    history = client.get("/assignments").json()
    assert len(history) == 1 and history[0]["game"]["id"] == seen[-1]


def test_stale_tab_cannot_consume_another_attempt_or_accept_unseen_game(client):
    offer = roll(client, enter(client))
    assert client.post(f"/rolls/{offer['id']}/reroll", json={"attempt": 1}).status_code == 200
    for endpoint in ("reroll", "accept"):
        assert client.post(f"/rolls/{offer['id']}/{endpoint}", json={"attempt": 1}).status_code == 409
    state = client.get(f"/players/{offer['player_id']}/state").json()
    assert state["round"]["attempt"] == 2
    assert state["assignment"] is None


@pytest.mark.parametrize("status", ["completed", "dropped"])
def test_finish_with_comment_then_roll_again_without_repeats(client, status):
    player_id = enter(client)
    first = roll(client, player_id)
    second = client.post(f"/rolls/{first['id']}/reroll", json={"attempt": 1}).json()
    accepted = client.post(f"/rolls/{first['id']}/accept", json={"attempt": 2}).json()
    response = client.patch(f"/assignments/{accepted['id']}", json={"status": status, "spent_hours": 2.5, "comment": "  Хорошая игра!  "})
    assert response.status_code == 200
    next_offer = roll(client, player_id)
    assert next_offer["game"]["id"] not in (first["game"]["id"], second["game"]["id"])
    history = client.get("/assignments").json()
    assert history[0]["status"] == status
    assert history[0]["comment"] == "Хорошая игра!"
    assert history[0]["spent_hours"] == 2.5
    assert history[0]["player_name"] == "Тимофей"


def test_different_players_can_receive_same_game(client):
    first = roll(client, enter(client, "Тимофей"))
    second = roll(client, enter(client, "Друг"))
    assert first["game"]["id"] == second["game"]["id"]


def test_too_few_candidates_does_not_spend_attempt(client):
    player_id = enter(client)
    assert client.post("/rolls", json={"player_id": player_id, "max_hours": 4}).status_code == 409
    assert roll(client, player_id, max_hours=6)["game"]["id"] == 1


def test_state_survives_server_restart(tmp_path, games):
    path = tmp_path / "state.json"
    with TestClient(create_app(path, games)) as first:
        player_id = enter(first)
        offer = roll(first, player_id)
        offer = first.post(f"/rolls/{offer['id']}/reroll", json={"attempt": 1}).json()
    with TestClient(create_app(path, games)) as second:
        state = second.get(f"/players/{player_id}/state").json()
        assert state["round"] == offer
        last = second.post(f"/rolls/{offer['id']}/reroll", json={"attempt": 2}).json()
        assert last["accepted"] is True
        assignment = second.get("/assignments").json()[0]
        second.patch(f"/assignments/{assignment['id']}", json={"status": "completed", "spent_hours": 3.5, "comment": "История сохранится"})
    with TestClient(create_app(path, games)) as third:
        assert third.get("/assignments").json()[0]["comment"] == "История сохранится"
        assert third.get("/assignments").json()[0]["spent_hours"] == 3.5


def test_simultaneous_start_requests_create_one_round(client):
    player_id = enter(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: client.post("/rolls", json={"player_id": player_id}), range(2)))
    assert sorted(response.status_code for response in results) == [201, 409]
    assert client.get(f"/players/{player_id}/state").json()["round"]["attempt"] == 1


def test_unknown_records_and_invalid_status(client):
    assert client.get("/players/999/state").status_code == 404
    assert client.post("/rolls/999/accept", json={"attempt": 1}).status_code == 404
    assert client.patch("/assignments/999", json={"status": "completed", "spent_hours": 1}).status_code == 404
    assert client.patch("/assignments/999", json={"status": "playing"}).status_code == 422


@pytest.mark.parametrize("spent_hours", [-1, 10001, "nan", "inf", "abc", None])
def test_invalid_spent_hours_does_not_finish_game(client, spent_hours):
    player_id = enter(client)
    offer = roll(client, player_id)
    assignment = client.post(f"/rolls/{offer['id']}/accept", json={"attempt": 1}).json()
    response = client.patch(f"/assignments/{assignment['id']}",
                            json={"status": "completed", "spent_hours": spent_hours})
    assert response.status_code == 422
    assert client.get(f"/players/{player_id}/state").json()["assignment"]["status"] == "playing"
    assert client.get("/assignments").json()[0]["spent_hours"] is None


def test_finish_requires_hours_and_allows_zero_for_dropped_game(client):
    player_id = enter(client)
    offer = roll(client, player_id)
    assignment = client.post(f"/rolls/{offer['id']}/accept", json={"attempt": 1}).json()
    path = f"/assignments/{assignment['id']}"
    assert client.patch(path, json={"status": "dropped"}).status_code == 422
    response = client.patch(path, json={"status": "dropped", "spent_hours": 0})
    assert response.status_code == 200
    assert response.json()["spent_hours"] == 0
    # Повторное сохранение не должно менять уже записанный результат.
    assert client.patch(path, json={"status": "completed", "spent_hours": 5}).status_code == 409
    assert client.get("/assignments").json()[0]["spent_hours"] == 0


def test_environment_and_logs(tmp_path, games, monkeypatch, caplog):
    path = tmp_path / "custom.json"
    catalogue = tmp_path / "my_games.json"
    catalogue.write_text(json.dumps(games), encoding="utf-8")
    monkeypatch.setenv("GAMES_FILE", str(catalogue))
    monkeypatch.setenv("GAME_ROLL_DATA", str(path))
    with caplog.at_level(logging.INFO, logger="game_roll"):
        with TestClient(create_app()) as client:
            assert client.get("/games").json() == games
            client.get("/health")
    assert path.exists()
    assert "Service started:" in caplog.text
    assert "GET /health status=200" in caplog.text
    assert "Service stopped" in caplog.text


def test_corrupt_history_is_not_erased(tmp_path, games):
    path = tmp_path / "state.json"
    path.write_text("broken json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        with TestClient(create_app(path, games)):
            pass
    assert path.read_text(encoding="utf-8") == "broken json"
