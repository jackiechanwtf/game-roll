"""Подготовить небольшой каталог из CSV или ZIP открытого датасета HLTB."""

import argparse
import csv
import io
import json
from pathlib import Path
from zipfile import ZipFile


def prepare(rows, limit=500):
    games = {}
    for row in rows:
        platforms = [value.strip() for value in row["game_profile_platform"].split(",")]
        seconds = float(row["game_comp_main"] or 0)
        submissions = int(float(row["game_comp_main_count"] or 0))
        if (
            "PC" not in platforms
            or row["game_game_type"] != "game"
            or seconds <= 0
            or submissions < 100
        ):
            continue
        game_id = int(row["game_game_id"])
        games[game_id] = {
            "id": game_id,
            "name": row["game_game_name"].strip(),
            "hours": round(seconds / 3600, 1),
            "genres": row["game_profile_genre"],
            "submissions": submissions,
            "source_url": f"https://howlongtobeat.com/game/{game_id}",
        }
    popular = sorted(games.values(), key=lambda game: (-game["submissions"], game["id"]))
    return sorted(popular[:limit], key=lambda game: game["name"].casefold())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="hltb_data.csv или ZIP с этим файлом")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent / "games.json")
    args = parser.parse_args()
    if args.source.suffix.lower() == ".zip":
        with ZipFile(args.source) as archive:
            with archive.open("hltb_data.csv") as source:
                games = prepare(csv.DictReader(io.TextIOWrapper(source, encoding="utf-8-sig")), args.limit)
    else:
        with args.source.open(encoding="utf-8-sig", newline="") as source:
            games = prepare(csv.DictReader(source), args.limit)
    args.output.write_text(json.dumps(games, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Сохранено {len(games)} ПК-игр: {args.output}")


if __name__ == "__main__":
    main()
