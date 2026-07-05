"""GitHub ツール群 — 調査官が function calling で自律的に呼ぶ道具。

- blame は REST に無いので GraphQL、それ以外は REST
- 全応答は Cache を通す（デモ中のレート制限対策）
- 各ツールは Evidence と「次の掘り先の手がかり」（PR番号・参照Issue番号）を返す
"""

import re
from pathlib import Path

import httpx
from pydantic import BaseModel

from .cache import Cache
from .models import Evidence

API = "https://api.github.com"

_BLAME_QUERY = """
query($owner: String!, $repo: String!, $ref: String!, $path: String!) {
  repository(owner: $owner, name: $repo) {
    object(expression: $ref) {
      ... on Commit {
        blame(path: $path) {
          ranges {
            startingLine
            endingLine
            commit {
              oid
              messageHeadline
              url
              author { name date }
            }
          }
        }
      }
    }
  }
}
"""

_ISSUE_REF = re.compile(r"#(\d+)")


class BlameResult(BaseModel):
    evidence: Evidence


class CommitResult(BaseModel):
    evidence: Evidence
    pr_numbers: list[int]


class PrResult(BaseModel):
    evidence: Evidence
    comments: list[Evidence]
    referenced_issues: list[int]


class IssueResult(BaseModel):
    evidence: Evidence
    comments: list[Evidence]


class GitHubToolbox:
    def __init__(
        self,
        token: str,
        cache: Cache | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._cache = cache or Cache(Path("/tmp/code-archaeologist-cache"))
        self._client = httpx.Client(
            transport=transport,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=30,
        )

    def _get(self, path: str) -> dict | list:
        cached = self._cache.get(path)
        if cached is not None:
            return cached
        response = self._client.get(f"{API}{path}")
        response.raise_for_status()
        data = response.json()
        self._cache.set(path, data)
        return data

    def _graphql(self, query: str, variables: dict) -> dict:
        key = f"graphql:{query}:{sorted(variables.items())}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        response = self._client.post(
            f"{API}/graphql", json={"query": query, "variables": variables}
        )
        response.raise_for_status()
        data = response.json()
        self._cache.set(key, data)
        return data

    def blame_line(
        self, owner: str, repo: str, path: str, line: int, ref: str = "HEAD"
    ) -> BlameResult:
        """指定行を最後に変更したコミットを特定する（遡行の起点）。"""
        data = self._graphql(
            _BLAME_QUERY, {"owner": owner, "repo": repo, "ref": ref, "path": path}
        )
        ranges = data["data"]["repository"]["object"]["blame"]["ranges"]
        for r in ranges:
            if r["startingLine"] <= line <= r["endingLine"]:
                commit = r["commit"]
                return BlameResult(
                    evidence=Evidence(
                        kind="blame",
                        ref=commit["oid"],
                        url=commit["url"],
                        title=commit["messageHeadline"],
                        detail=f"{path}:{line} を最後に変更したコミット",
                        author=commit["author"]["name"],
                        date=commit["author"]["date"],
                    )
                )
        raise ValueError(f"line {line} not found in blame ranges for {path}")

    def get_commit(self, owner: str, repo: str, sha: str) -> CommitResult:
        """コミット全文と、紐づく PR 番号を取得する。"""
        data = self._get(f"/repos/{owner}/{repo}/commits/{sha}")
        pulls = self._get(f"/repos/{owner}/{repo}/commits/{sha}/pulls")
        return CommitResult(
            evidence=Evidence(
                kind="commit",
                ref=data["sha"],
                url=data["html_url"],
                title=data["commit"]["message"].splitlines()[0],
                detail=data["commit"]["message"],
                author=data["commit"]["author"]["name"],
                date=data["commit"]["author"]["date"],
            ),
            pr_numbers=[p["number"] for p in pulls],
        )

    def get_pr(self, owner: str, repo: str, number: int) -> PrResult:
        """PR 本文・議論コメントと、そこで参照されている Issue 番号を取得する。"""
        pr = self._get(f"/repos/{owner}/{repo}/pulls/{number}")
        raw_comments = self._get(f"/repos/{owner}/{repo}/issues/{number}/comments")
        comments = [
            Evidence(
                kind="pr_comment",
                ref=str(number),
                url=c["html_url"],
                title=(c["body"] or "").splitlines()[0][:120],
                detail=c["body"] or "",
                author=c["user"]["login"],
                date=c["created_at"],
            )
            for c in raw_comments
        ]
        texts = [pr.get("body") or ""] + [(c["body"] or "") for c in raw_comments]
        referenced = {
            int(m) for text in texts for m in _ISSUE_REF.findall(text)
        } - {number}
        return PrResult(
            evidence=Evidence(
                kind="pull_request",
                ref=str(number),
                url=pr["html_url"],
                title=pr["title"],
                detail=pr.get("body") or "",
                author=pr["user"]["login"],
                date=pr["created_at"],
            ),
            comments=comments,
            referenced_issues=sorted(referenced),
        )

    def get_issue(self, owner: str, repo: str, number: int) -> IssueResult:
        """Issue 本文とコメントを取得する。"""
        issue = self._get(f"/repos/{owner}/{repo}/issues/{number}")
        raw_comments = self._get(f"/repos/{owner}/{repo}/issues/{number}/comments")
        comments = [
            Evidence(
                kind="issue_comment",
                ref=str(number),
                url=c["html_url"],
                title=(c["body"] or "").splitlines()[0][:120],
                detail=c["body"] or "",
                author=c["user"]["login"],
                date=c["created_at"],
            )
            for c in raw_comments
        ]
        return IssueResult(
            evidence=Evidence(
                kind="issue",
                ref=str(number),
                url=issue["html_url"],
                title=issue["title"],
                detail=issue.get("body") or "",
                author=issue["user"]["login"],
                date=issue["created_at"],
            ),
            comments=comments,
        )
