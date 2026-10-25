"""Чтение и запись состояния в обычный JSON-файл. Сервер работает одним процессом."""

from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
from threading import RLock


class JsonStorage:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()
        if not self.path.exists():
            self._write({"players": [], "rounds": [], "assignments": []})
        # Повреждённый файл нельзя молча заменить пустой историей.
        self.read()

    def read(self):
        with self.lock:
            return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, data):
        temporary = None
        try:
            # Замена готовым файлом защищает историю от частично записанного JSON.
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent, delete=False
            ) as output:
                temporary = Path(output.name)
                json.dump(data, output, ensure_ascii=False, indent=2)
                output.write("\n")
            temporary.replace(self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    @contextmanager
    def transaction(self):
        # Запросы разных друзей выполняются по очереди и не затирают друг друга.
        with self.lock:
            data = self.read()
            yield data
            self._write(data)
