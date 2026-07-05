"""GitHub ツール群: 調査官が function calling で呼ぶ道具。全応答はキャッシュを通す。

テストは httpx.MockTransport を注入し、実 API には触れない。
"""

import json

import httpx
import pytest

from code_archaeologist.cache import Cache
from code_archaeologist.github_tools import GitHubToolbox

BLAME_GRAPHQL_RESPONSE = {
    "data": {
        "repository": {
            "object": {
                "blame": {
                    "ranges": [
                        {
                            "startingLine": 1,
                            "endingLine": 3,
                            "commit": {
                                "oid": "aaa111",
                                "messageHeadline": "initial import",
                                "url": "https://github.com/o/r/commit/aaa111",
                                "author": {"name": "bob", "date": "2018-01-01T00:00:00Z"},
                            },
                        },
                        {
                            "startingLine": 4,
                            "endingLine": 6,
                            "commit": {
                                "oid": "bbb222",
                                "messageHeadline": "fix: sleep(3) to avoid race (#42)",
                                "url": "https://github.com/o/r/commit/bbb222",
                                "author": {"name": "alice", "date": "2019-03-01T00:00:00Z"},
                            },
                        },
                    ]
                }
            }
        }
    }
}


@pytest.fixture
def requests_seen():
    return []


@pytest.fixture
def toolbox(tmp_path, requests_seen):
    def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(request)
        path = request.url.path
        if path == "/graphql":
            return httpx.Response(200, json=BLAME_GRAPHQL_RESPONSE)
        if path == "/repos/o/r/commits/bbb222":
            return httpx.Response(
                200,
                json={
                    "sha": "bbb222",
                    "html_url": "https://github.com/o/r/commit/bbb222",
                    "commit": {
                        "message": "fix: sleep(3) to avoid race (#42)\n\nUpstream API returns before write is visible.",
                        "author": {"name": "alice", "date": "2019-03-01T00:00:00Z"},
                    },
                },
            )
        if path == "/repos/o/r/commits/bbb222/pulls":
            return httpx.Response(
                200, json=[{"number": 42, "title": "Workaround for upstream flakiness"}]
            )
        if path == "/repos/o/r/pulls/42":
            return httpx.Response(
                200,
                json={
                    "number": 42,
                    "title": "Workaround for upstream flakiness",
                    "body": "Fixes #12 — upstream eventual consistency breaks CI.",
                    "html_url": "https://github.com/o/r/pull/42",
                    "user": {"login": "alice"},
                    "created_at": "2019-02-28T00:00:00Z",
                },
            )
        if path == "/repos/o/r/issues/42/comments":
            return httpx.Response(
                200,
                json=[
                    {
                        "body": "See also #7 for the original report",
                        "html_url": "https://github.com/o/r/pull/42#issuecomment-1",
                        "user": {"login": "carol"},
                        "created_at": "2019-02-28T10:00:00Z",
                    }
                ],
            )
        if path == "/repos/o/r/issues/12":
            return httpx.Response(
                200,
                json={
                    "number": 12,
                    "title": "CI flaky: read-after-write fails",
                    "body": "Upstream API is eventually consistent",
                    "html_url": "https://github.com/o/r/issues/12",
                    "user": {"login": "dave"},
                    "created_at": "2019-02-01T00:00:00Z",
                },
            )
        if path == "/repos/o/r/issues/12/comments":
            return httpx.Response(200, json=[])
        if path == "/repos/o/r/contents/src/api.py":
            import base64

            content = base64.b64encode(b"import time\n\ntime.sleep(3)\n").decode()
            return httpx.Response(
                200, json={"content": content, "encoding": "base64"}
            )
        return httpx.Response(404, json={"message": "not found"})

    return GitHubToolbox(
        token="dummy",
        cache=Cache(tmp_path),
        transport=httpx.MockTransport(handler),
    )


def test_blame_line_returns_commit_covering_line(toolbox):
    result = toolbox.blame_line("o", "r", "src/api.py", line=5)
    assert result.evidence.ref == "bbb222"
    assert result.evidence.kind == "blame"
    assert "sleep(3)" in result.evidence.title


def test_blame_sends_auth_and_query(toolbox, requests_seen):
    toolbox.blame_line("o", "r", "src/api.py", line=5)
    request = requests_seen[0]
    assert request.headers["authorization"] == "Bearer dummy"
    body = json.loads(request.content)
    assert "blame" in body["query"]


def test_get_commit_returns_evidence_and_pr_numbers(toolbox):
    result = toolbox.get_commit("o", "r", "bbb222")
    assert result.evidence.kind == "commit"
    assert "Upstream API" in result.evidence.detail
    assert result.pr_numbers == [42]


def test_get_commit_second_call_hits_cache(toolbox, requests_seen):
    toolbox.get_commit("o", "r", "bbb222")
    first_count = len(requests_seen)
    toolbox.get_commit("o", "r", "bbb222")
    assert len(requests_seen) == first_count


def test_get_pr_returns_discussion_and_referenced_issues(toolbox):
    result = toolbox.get_pr("o", "r", 42)
    assert result.evidence.kind == "pull_request"
    assert result.evidence.author == "alice"
    assert len(result.comments) == 1
    assert result.comments[0].kind == "pr_comment"
    # 本文の #12 とコメントの #7 を拾い、自分自身 (#42) は含めない
    assert sorted(result.referenced_issues) == [7, 12]


def test_get_file_returns_decoded_text(toolbox):
    # UI の左ペイン（対象行ハイライト付きコード表示）用
    text = toolbox.get_file("o", "r", "src/api.py")
    assert text == "import time\n\ntime.sleep(3)\n"


def test_get_issue_returns_evidence(toolbox):
    result = toolbox.get_issue("o", "r", 12)
    assert result.evidence.kind == "issue"
    assert result.evidence.title == "CI flaky: read-after-write fails"
    assert result.comments == []
