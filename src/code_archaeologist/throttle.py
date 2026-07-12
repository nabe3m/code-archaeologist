"""匿名アクセスのコスト対策 — 同時実行数と IP あたりレートを制限する。

公開エンドポイント（--allow-unauthenticated）で LLM 駆動の高コストな調査を
匿名で無制限に回されないための最小防御。プロセス内状態のみ（外部依存なし）で、
Cloud Run インスタンスごとに効く。`--max-instances` と併用して総コストを上限する。

- 同時実行スロット: 並列に走る調査の本数を上限（在庫切れなら "busy"）
- IP あたりレート: 一定時間窓での起動回数を上限（超過なら "rate"）
"""

import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable

# X-Forwarded-For を詐称した大量の別 IP でメモリを膨らまされないための掃除閾値
_SWEEP_THRESHOLD = 1024


class Throttle:
    def __init__(
        self,
        max_concurrent: int,
        per_ip_limit: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_concurrent = max_concurrent
        self._per_ip_limit = per_ip_limit
        self._window = window_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._active = 0
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def try_acquire(self, ip: str) -> str | None:
        """スロット取得を試みる。拒否理由（"rate" / "busy"）を返し、取得できたら None。

        None が返った場合、呼び出し側は処理完了時に必ず release() すること。
        """
        now = self._clock()
        with self._lock:
            if len(self._hits) > _SWEEP_THRESHOLD:
                self._sweep(now)
            hits = self._hits[ip]
            # スライディングウィンドウ: 窓の外に出た起動履歴を捨てる
            while hits and hits[0] <= now - self._window:
                hits.popleft()
            if len(hits) >= self._per_ip_limit:
                if not hits:  # defaultdict が作った空 deque を残さない
                    del self._hits[ip]
                return "rate"
            # 同時実行が満杯なら IP 履歴を汚さずに（＝この試行を数えず）断る
            if self._active >= self._max_concurrent:
                if not hits:
                    del self._hits[ip]
                return "busy"
            hits.append(now)
            self._active += 1
            return None

    def release(self) -> None:
        with self._lock:
            if self._active > 0:
                self._active -= 1

    def _sweep(self, now: float) -> None:
        """窓を過ぎた IP 履歴を破棄する（ロック保持中に呼ぶこと）。"""
        stale = [
            ip for ip, h in self._hits.items() if not h or h[-1] <= now - self._window
        ]
        for ip in stale:
            del self._hits[ip]
