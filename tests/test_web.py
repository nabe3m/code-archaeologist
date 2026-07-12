"""Web エンドポイントのガード: 監査(書き込み)は許可リスト内 repo のみ。

公開エンドポイント（--allow-unauthenticated）で匿名の誰でも叩けるため、
共有トークンによる任意 repo への PR 乱造を repo 許可リストで防いでいる。
"""

from fastapi.testclient import TestClient

from code_archaeologist import web
from code_archaeologist.throttle import Throttle


def _client() -> TestClient:
    return TestClient(web.app)


def test_audit_rejects_repo_outside_allowlist(monkeypatch):
    monkeypatch.setattr(web, "_AUDIT_ALLOWLIST", {"nabe3m/demo-repo"})
    resp = _client().get("/api/audit", params={"repo": "attacker/target", "path": "x.py"})
    assert resp.status_code == 403


def test_audit_rejects_malformed_repo(monkeypatch):
    monkeypatch.setattr(web, "_AUDIT_ALLOWLIST", {"nabe3m/demo-repo"})
    resp = _client().get("/api/audit", params={"repo": "no-slash", "path": "x.py"})
    assert resp.status_code == 400


def test_audit_allowlist_is_case_insensitive(monkeypatch):
    # 許可リストは lower 正規化して比較する（大文字混じりでも許可判定は同じ）
    monkeypatch.setattr(web, "_AUDIT_ALLOWLIST", {"nabe3m/demo-repo"})
    # 許可外は大文字でも 403 のまま
    resp = _client().get("/api/audit", params={"repo": "Attacker/Target", "path": "x.py"})
    assert resp.status_code == 403


def _always_busy() -> Throttle:
    # max_concurrent=0 → 常に "busy" を返すスロットル（レート枠は消費しない）
    return Throttle(max_concurrent=0, per_ip_limit=100, window_seconds=60)


def test_dig_returns_429_when_throttled(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setenv("GITHUB_TOKEN", "test")
    monkeypatch.setattr(web, "_THROTTLE", _always_busy())
    resp = _client().get(
        "/api/dig", params={"repo": "any/repo", "path": "x.py", "line": 1, "q": "?"}
    )
    assert resp.status_code == 429


def test_audit_returns_429_when_throttled(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setenv("GITHUB_TOKEN", "test")
    monkeypatch.setattr(web, "_AUDIT_ALLOWLIST", {"nabe3m/demo-repo"})
    monkeypatch.setattr(web, "_THROTTLE", _always_busy())
    resp = _client().get(
        "/api/audit", params={"repo": "nabe3m/demo-repo", "path": "x.py"}
    )
    assert resp.status_code == 429
