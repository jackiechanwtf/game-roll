# Game Roll

Небольшой сервис для друзей: случайно выбрать ПК-игру и сохранить её в общей таблице.

## Запуск

Нужен Python 3.10 или новее.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn app_final:app
```

Приложение: http://127.0.0.1:8000. Документация API: http://127.0.0.1:8000/docs.
