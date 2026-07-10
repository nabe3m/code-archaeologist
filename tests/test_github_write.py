"""GitHub 書き込みツール: 監査官が削除 PR を実作成するための道具。

読み取り系と違い、書き込みフローの GET（ref/contents）はキャッシュを通さない
（古い sha でコミットすると 409 になるため）。
"""

import base64
import json

import httpx
import pytest

from code_archaeologist.cache import Cache
from code_archaeologist.github_tools import GitHubToolbox

FILE_CONTENT = "line1\nline2 to remove\nline3\n"


@pytest.fixture
def write_log():
    return []


@pytest.fixture
def toolbox(tmp_path, write_log):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method in ("POST", "PUT"):
            write_log.append((request.method, path, json.loads(request.content)))
        if path == "/repos/o/r" and request.method == "GET":
            return httpx.Response(200, json={"default_branch": "main"})
        if path == "/repos/o/r/git/ref/heads/main":
            return httpx.Response(200, json={"object": {"sha": "headsha123"}})
        if path == "/repos/o/r/git/refs" and request.method == "POST":
            return httpx.Response(201, json={"ref": "refs/heads/audit/x"})
        if path == "/repos/o/r/contents/orders/api.py":
            if request.method == "GET":
                return httpx.Response(
                    200,
                    json={
                        "content": base64.b64encode(FILE_CONTENT.encode()).decode(),
                        "encoding": "base64",
                        "sha": "filesha456",
                    },
                )
            return httpx.Response(200, json={"commit": {"sha": "newsha"}})
        if path == "/repos/o/r/issues/9/comments" and request.method == "POST":
            return httpx.Response(
                201,
                json={"html_url": "https://github.com/o/r/pull/9#issuecomment-42"},
            )
        if path == "/repos/o/r/pulls" and request.method == "POST":
            return httpx.Response(
                201, json={"number": 9, "html_url": "https://github.com/o/r/pull/9"}
            )
        return httpx.Response(404, json={"message": f"not found: {request.method} {path}"})

    return GitHubToolbox(
        token="dummy", cache=Cache(tmp_path), transport=httpx.MockTransport(handler)
    )


def test_create_deletion_pr_returns_pr_info(toolbox):
    result = toolbox.create_deletion_pr(
        "o",
        "r",
        path="orders/api.py",
        lines=[2],
        branch="audit/remove-sleep",
        title="chore: remove expired workaround",
        body="根拠: ...",
        commit_message="chore: remove expired workaround",
    )
    assert result == {"number": 9, "url": "https://github.com/o/r/pull/9"}


def test_create_deletion_pr_removes_exact_lines_and_targets_branch(toolbox, write_log):
    toolbox.create_deletion_pr(
        "o", "r", path="orders/api.py", lines=[2], branch="audit/remove-sleep",
        title="t", body="b", commit_message="m",
    )
    methods = [(m, p) for m, p, _ in write_log]
    assert methods == [
        ("POST", "/repos/o/r/git/refs"),
        ("PUT", "/repos/o/r/contents/orders/api.py"),
        ("POST", "/repos/o/r/pulls"),
    ]
    ref_body = write_log[0][2]
    assert ref_body == {"ref": "refs/heads/audit/remove-sleep", "sha": "headsha123"}
    put_body = write_log[1][2]
    assert base64.b64decode(put_body["content"]).decode() == "line1\nline3\n"
    assert put_body["branch"] == "audit/remove-sleep"
    assert put_body["sha"] == "filesha456"
    pr_body = write_log[2][2]
    assert pr_body["head"] == "audit/remove-sleep"
    assert pr_body["base"] == "main"


def test_post_pr_comment_returns_comment_url(toolbox, write_log):
    result = toolbox.post_pr_comment("o", "r", 9, "🔮 予言")
    assert result == {"url": "https://github.com/o/r/pull/9#issuecomment-42"}
    assert ("POST", "/repos/o/r/issues/9/comments") in [(m, p) for m, p, _ in write_log]
    assert write_log[-1][2] == {"body": "🔮 予言"}
