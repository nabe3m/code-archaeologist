"""証拠チェーンと構造化イベント。

調査官（発行）・史官（消費）・UI/SSE（表示）の3者がこの語彙を共有する。
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

EvidenceKind = Literal[
    "blame", "commit", "pull_request", "pr_comment", "issue", "issue_comment"
]

EventType = Literal[
    "dig_started",
    "dig_decision",
    "evidence_found",
    "answer",
    "done",
    "error",
    # 監査官
    "audit_candidate",
    "verdict",
    "pr_created",
    "oracle",
]


class Evidence(BaseModel):
    kind: EvidenceKind
    ref: str  # コミット SHA / PR・Issue 番号など
    url: str
    title: str
    detail: str = ""
    author: str = ""
    date: str = ""

    def label(self) -> str:
        if self.kind in ("pull_request", "issue"):
            return f"{self.kind} #{self.ref}"
        return f"{self.kind} {self.ref}"


class EvidenceChain(BaseModel):
    items: list[Evidence] = Field(default_factory=list)

    def add(self, evidence: Evidence) -> bool:
        """(kind, URL) で重複排除して追加。新規なら True。

        blame とコミットは同じ URL を指すが、コミット側はフルメッセージを
        持つ別証拠なので kind も鍵に含める。
        """
        if any(e.kind == evidence.kind and e.url == evidence.url for e in self.items):
            return False
        self.items.append(evidence)
        return True

    def __len__(self) -> int:
        return len(self.items)

    def as_context(self) -> str:
        """史官プロンプト用の番号付き証拠リスト。番号は出典引用 [n] に対応。"""
        lines = []
        for i, e in enumerate(self.items, start=1):
            lines.append(
                f"[{i}] {e.label()} — {e.title}\n"
                f"    author: {e.author}  date: {e.date}\n"
                f"    url: {e.url}\n"
                f"    {e.detail}"
            )
        return "\n".join(lines)


class DigEvent(BaseModel):
    type: EventType
    payload: dict[str, Any] = Field(default_factory=dict)


class Prophecy(BaseModel):
    """Oracle の予言 — 削除されるコードがかつて守っていた障害の記録。

    guarded_incident の主張には証拠番号 [n] を付ける(番号は削除 PR 本文の
    「発掘された証拠」リストに対応)。
    """

    guarded_incident: str
    recurrence_symptoms: str
    rollback_hint: str
