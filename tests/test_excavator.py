"""遡行ループ: LLM（注入された decide 関数）が各ステップの掘り先を自律判断し、
構造化イベントを発行する。停止条件 = finish 判断 or max_steps。
"""

from code_archaeologist.excavator import Decision, Excavator
from code_archaeologist.github_tools import (
    BlameResult,
    CommitResult,
    IssueResult,
    PrResult,
)
from code_archaeologist.models import Evidence


def ev(kind, ref, **overrides):
    defaults = dict(
        url=f"https://github.com/o/r/{kind}/{ref}",
        title=f"{kind} {ref} title",
        detail="detail",
        author="alice",
        date="2019-03-01",
    )
    return Evidence(kind=kind, ref=str(ref), **{**defaults, **overrides})


class StubToolbox:
    """github_tools と同じ表面。呼び出しを記録する。"""

    def __init__(self):
        self.calls = []

    def blame_line(self, owner, repo, path, line, ref="HEAD"):
        self.calls.append("blame_line")
        return BlameResult(evidence=ev("blame", "bbb222"))

    def get_commit(self, owner, repo, sha):
        self.calls.append("get_commit")
        return CommitResult(evidence=ev("commit", sha), pr_numbers=[42])

    def get_pr(self, owner, repo, number):
        self.calls.append("get_pr")
        return PrResult(
            evidence=ev("pull_request", number),
            comments=[ev("pr_comment", number, url="https://github.com/o/r/pull/42#c1")],
            referenced_issues=[12],
        )

    def get_issue(self, owner, repo, number):
        self.calls.append("get_issue")
        return IssueResult(evidence=ev("issue", number), comments=[])


def scripted_decider(decisions):
    """事前に台本化した判断列を順に返す decide 関数。受け取った文脈も記録する。"""
    seen_contexts = []
    iterator = iter(decisions)

    def decide(question, chain, leads):
        seen_contexts.append((chain.model_copy(deep=True), list(leads)))
        return next(iterator)

    decide.seen = seen_contexts
    return decide


def run_dig(toolbox, decide, max_steps=10):
    excavator = Excavator(toolbox=toolbox, decide=decide, max_steps=max_steps)
    return list(excavator.dig("o", "r", "src/api.py", 5, "なぜ sleep(3) があるの?"))


def test_events_flow_decision_then_evidence_then_done():
    decide = scripted_decider(
        [
            Decision(tool="blame_line", args={"path": "src/api.py", "line": 5}, reason="起点"),
            Decision(tool="get_commit", args={"sha": "bbb222"}, reason="blame先のコミットを読む"),
            Decision(tool="finish", args={}, reason="十分な証拠が揃った"),
        ]
    )
    events = run_dig(StubToolbox(), decide)
    types = [e.type for e in events]
    assert types == [
        "dig_started",
        "dig_decision",
        "evidence_found",
        "dig_decision",
        "evidence_found",
        "dig_decision",  # finish の判断も可視化する
        "done",
    ]
    assert events[1].payload["reason"] == "起点"
    assert events[-1].payload["evidence_count"] == 2


def test_done_payload_contains_chain():
    decide = scripted_decider(
        [
            Decision(tool="blame_line", args={"path": "src/api.py", "line": 5}, reason="起点"),
            Decision(tool="finish", args={}, reason="ok"),
        ]
    )
    events = run_dig(StubToolbox(), decide)
    done = events[-1]
    assert done.payload["chain"]["items"][0]["ref"] == "bbb222"


def test_stops_at_max_steps():
    decide = scripted_decider(
        [Decision(tool="get_commit", args={"sha": f"s{i}"}, reason="dig") for i in range(99)]
    )
    events = run_dig(StubToolbox(), decide, max_steps=3)
    assert events[-1].type == "done"
    assert events[-1].payload["stopped_by"] == "max_steps"
    assert sum(1 for e in events if e.type == "dig_decision") == 3


def test_duplicate_evidence_not_reemitted():
    decide = scripted_decider(
        [
            Decision(tool="get_commit", args={"sha": "bbb222"}, reason="1回目"),
            Decision(tool="get_commit", args={"sha": "bbb222"}, reason="2回目(重複)"),
            Decision(tool="finish", args={}, reason="ok"),
        ]
    )
    events = run_dig(StubToolbox(), decide)
    assert sum(1 for e in events if e.type == "evidence_found") == 1


def test_unknown_tool_emits_error_and_continues():
    decide = scripted_decider(
        [
            Decision(tool="warp_drive", args={}, reason="幻覚"),
            Decision(tool="finish", args={}, reason="ok"),
        ]
    )
    events = run_dig(StubToolbox(), decide)
    assert any(e.type == "error" for e in events)
    assert events[-1].type == "done"


def test_decider_sees_accumulated_evidence_and_leads():
    decide = scripted_decider(
        [
            Decision(tool="get_pr", args={"number": 42}, reason="PRを読む"),
            Decision(tool="finish", args={}, reason="ok"),
        ]
    )
    run_dig(StubToolbox(), decide)
    first_chain, _ = decide.seen[0]
    second_chain, second_leads = decide.seen[1]
    assert len(first_chain) == 0
    assert len(second_chain) == 2  # PR 本文 + コメント
    # PR が参照していた Issue #12 が「次の掘り先候補」として提示される
    assert {"tool": "get_issue", "args": {"number": 12}} in second_leads
