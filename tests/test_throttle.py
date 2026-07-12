"""スロットリング: 同時実行数と IP あたりレートの制限。

時刻はテスト用に注入したクロックで進める（実時間に依存しない）。
"""

from code_archaeologist.throttle import Throttle


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def test_concurrency_limit_blocks_then_frees_on_release():
    clock = Clock()
    t = Throttle(max_concurrent=2, per_ip_limit=100, window_seconds=60, clock=clock)
    assert t.try_acquire("a") is None
    assert t.try_acquire("b") is None
    # 3本目は同時実行が満杯で "busy"
    assert t.try_acquire("c") == "busy"
    # 1本解放すれば次が入れる
    t.release()
    assert t.try_acquire("c") is None


def test_per_ip_rate_limit_within_window():
    clock = Clock()
    t = Throttle(max_concurrent=100, per_ip_limit=2, window_seconds=60, clock=clock)
    assert t.try_acquire("1.2.3.4") is None
    t.release()
    assert t.try_acquire("1.2.3.4") is None
    t.release()
    # 同一 IP の3回目は窓内なので "rate"
    assert t.try_acquire("1.2.3.4") == "rate"
    # 別 IP は独立に許可される
    assert t.try_acquire("5.6.7.8") is None


def test_rate_window_slides():
    clock = Clock()
    t = Throttle(max_concurrent=100, per_ip_limit=1, window_seconds=60, clock=clock)
    assert t.try_acquire("ip") is None
    t.release()
    assert t.try_acquire("ip") == "rate"
    # 窓を越えれば履歴が失効して再び許可
    clock.t = 61.0
    assert t.try_acquire("ip") is None


def test_busy_does_not_consume_ip_budget():
    # 同時実行満杯で断られた試行は IP レートを消費しない
    clock = Clock()
    t = Throttle(max_concurrent=1, per_ip_limit=1, window_seconds=60, clock=clock)
    assert t.try_acquire("ip") is None  # 1本占有（IP 予算も1消費）
    assert t.try_acquire("other") == "busy"  # 満杯 → busy、other の予算は無傷
    t.release()
    assert t.try_acquire("other") is None
