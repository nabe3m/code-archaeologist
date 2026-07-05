"""GitHub API 応答の2層キャッシュ（メモリ + ディスク）。

デモ中に GitHub API のレート制限で死なないよう、取得結果は必ずここを通す。
キーは API パス等の任意文字列。ディスク上は SHA-256 でファイル名衝突を防ぐ。
"""

import hashlib
import json
from pathlib import Path
from typing import Any


class Cache:
    def __init__(self, directory: Path | str) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._memory: dict[str, Any] = {}

    def _path(self, key: str) -> Path:
        return self._dir / (hashlib.sha256(key.encode()).hexdigest() + ".json")

    def get(self, key: str) -> Any | None:
        if key in self._memory:
            return self._memory[key]
        path = self._path(key)
        if path.exists():
            value = json.loads(path.read_text())
            self._memory[key] = value
            return value
        return None

    def set(self, key: str, value: Any) -> None:
        self._memory[key] = value
        self._path(key).write_text(json.dumps(value, ensure_ascii=False))
