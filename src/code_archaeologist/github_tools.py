"""GitHub ツール群 — 調査官が function calling で自律的に呼ぶ道具。

- blame は REST に無いので GraphQL、それ以外は REST
- 全応答は Cache を通す（デモ中のレート制限対策）
- 各ツールは Evidence と「次の掘り先の手がかり」（PR番号・参照Issue番号）を返す
"""

import base64
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
        self._head_cache: dict[tuple[str, str], str] = {}
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

    def _blame_ranges(self, owner: str, repo: str, path: str, ref: str) -> list[dict]:
        ref = self._resolve_ref(owner, repo, ref)
        data = self._graphql(
            _BLAME_QUERY, {"owner": owner, "repo": repo, "ref": ref, "path": path}
        )
        return data["data"]["repository"]["object"]["blame"]["ranges"]

    def blame_line(
        self, owner: str, repo: str, path: str, line: int, ref: str = "HEAD"
    ) -> BlameResult:
        """指定行を最後に変更したコミットを特定する（遡行の起点）。"""
        for r in self._blame_ranges(owner, repo, path, ref):
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

    def blame_range(
        self, owner: str, repo: str, path: str, start: int, end: int, ref: str = "HEAD"
    ) -> list[Evidence]:
        """行範囲をカバーするコミット群を重複排除して返す（範囲遡行の起点）。"""
        evidences: list[Evidence] = []
        seen: set[str] = set()
        for r in self._blame_ranges(owner, repo, path, ref):
            if r["endingLine"] < start or r["startingLine"] > end:
                continue
            commit = r["commit"]
            if commit["oid"] in seen:
                continue
            seen.add(commit["oid"])
            span_start = max(r["startingLine"], start)
            span_end = min(r["endingLine"], end)
            evidences.append(
                Evidence(
                    kind="blame",
                    ref=commit["oid"],
                    url=commit["url"],
                    title=commit["messageHeadline"],
                    detail=f"{path}:{span_start}-{span_end} を最後に変更したコミット",
                    author=commit["author"]["name"],
                    date=commit["author"]["date"],
                )
            )
        if not evidences:
            raise ValueError(f"lines {start}-{end} not found in blame ranges for {path}")
        return evidences

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

    def _get_fresh(self, path: str) -> dict | list:
        """キャッシュを通さない GET（書き込みフロー用。古い sha を掴むと 409 になる）。"""
        response = self._client.get(f"{API}{path}")
        response.raise_for_status()
        return response.json()

    def _resolve_ref(self, owner: str, repo: str, ref: str) -> str:
        """HEAD を実コミット SHA に解決する（インスタンス内で1回だけ取得）。

        キャッシュキーを SHA 単位にすることで、リポジトリ更新後に
        古い blame/ファイル内容を返し続けるステイルを防ぐ。
        """
        if ref != "HEAD":
            return ref
        key = (owner, repo)
        if key not in self._head_cache:
            self._head_cache[key] = self._get_fresh(
                f"/repos/{owner}/{repo}/commits/HEAD"
            )["sha"]
        return self._head_cache[key]

    def _post(self, path: str, payload: dict) -> dict:
        response = self._client.post(f"{API}{path}", json=payload)
        response.raise_for_status()
        return response.json()

    def create_deletion_pr(
        self,
        owner: str,
        repo: str,
        path: str,
        lines: list[int],
        branch: str,
        title: str,
        body: str,
        commit_message: str,
    ) -> dict:
        """指定行を削除するブランチ + コミット + PR を作成する（監査官の出口）。

        lines は 1 始まりの行番号。デフォルトブランチを起点にする。
        """
        base = self._get_fresh(f"/repos/{owner}/{repo}")["default_branch"]
        head_sha = self._get_fresh(f"/repos/{owner}/{repo}/git/ref/heads/{base}")["object"]["sha"]
        self._post(
            f"/repos/{owner}/{repo}/git/refs",
            {"ref": f"refs/heads/{branch}", "sha": head_sha},
        )

        file_info = self._get_fresh(f"/repos/{owner}/{repo}/contents/{path}?ref={base}")
        original = base64.b64decode(file_info["content"]).decode()
        remove = set(lines)
        kept = [
            text
            for i, text in enumerate(original.splitlines(keepends=True), start=1)
            if i not in remove
        ]
        response = self._client.put(
            f"{API}/repos/{owner}/{repo}/contents/{path}",
            json={
                "message": commit_message,
                "content": base64.b64encode("".join(kept).encode()).decode(),
                "sha": file_info["sha"],
                "branch": branch,
            },
        )
        response.raise_for_status()

        pr = self._post(
            f"/repos/{owner}/{repo}/pulls",
            {"title": title, "body": body, "head": branch, "base": base},
        )
        return {"number": pr["number"], "url": pr["html_url"]}

    def post_pr_comment(self, owner: str, repo: str, number: int, body: str) -> dict:
        """PR にコメントを投稿する(Oracle の予言の出口)。PR コメントは Issues API を使う。"""
        data = self._post(f"/repos/{owner}/{repo}/issues/{number}/comments", {"body": body})
        return {"url": data["html_url"]}

    def search_issues(self, owner: str, repo: str, query: str) -> list[dict]:
        """リポジトリ内の Issue/PR をキーワード検索する。

        「当時の制約はその後解消されたか?」を追跡するための前方調査ツール。
        結果は掘り先候補（get_issue / get_pr）への入口になる。
        """
        q = f"repo:{owner}/{repo} {query}"
        data = self._get(f"/search/issues?q={q}&per_page=10")
        return [
            {
                "number": item["number"],
                "title": item["title"],
                "is_pr": "pull_request" in item,
                "state": item["state"],
                "url": item["html_url"],
            }
            for item in data["items"]
        ]

    def list_files(self, owner: str, repo: str) -> list[str]:
        """リポジトリの全ファイルパス（UI のファイルツリー用）。"""
        sha = self._resolve_ref(owner, repo, "HEAD")
        data = self._get(f"/repos/{owner}/{repo}/git/trees/{sha}?recursive=1")
        return [item["path"] for item in data["tree"] if item["type"] == "blob"]

    def get_file(self, owner: str, repo: str, path: str, ref: str = "HEAD") -> str:
        """ファイル本文を取得する（UI のコード表示用）。"""
        ref = self._resolve_ref(owner, repo, ref)
        data = self._get(f"/repos/{owner}/{repo}/contents/{path}?ref={ref}")
        return base64.b64decode(data["content"]).decode()

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
