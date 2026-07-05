"""GitHub API 応答キャッシュ: メモリ + ディスクの2層。デモ中のレート制限死を防ぐ。"""

from code_archaeologist.cache import Cache


def test_miss_returns_none(tmp_path):
    cache = Cache(tmp_path)
    assert cache.get("repos/o/r/commits/abc") is None


def test_set_then_get_returns_value(tmp_path):
    cache = Cache(tmp_path)
    cache.set("repos/o/r/commits/abc", {"sha": "abc", "message": "fix"})
    assert cache.get("repos/o/r/commits/abc") == {"sha": "abc", "message": "fix"}


def test_persists_across_instances(tmp_path):
    Cache(tmp_path).set("key/with/slashes", [1, 2, 3])
    fresh = Cache(tmp_path)
    assert fresh.get("key/with/slashes") == [1, 2, 3]


def test_keys_do_not_collide(tmp_path):
    cache = Cache(tmp_path)
    cache.set("a/b", "first")
    cache.set("a_b", "second")
    assert cache.get("a/b") == "first"
    assert cache.get("a_b") == "second"
