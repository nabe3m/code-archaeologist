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

    def search_issues(self, owner, repo, query):
        self.calls.append(f"search_issues({query})")
        return [
            {"number": 3, "title": "v2 移行", "is_pr": False, "state": "closed",
             "url": "https://github.com/o/r/issues/3"},
            {"number": 4, "title": "v2 へ移行", "is_pr": True, "state": "closed",
             "url": "https://github.com/o/r/pull/4"},
        ]


def scripted_decider(decisions):
    """事前に台本化した判断列を順に返す decide 関数。受け取った文脈も記録する。"""
    seen_contexts = []
    iterator = iter(decisions)

    def decide(question, chain, leads, target, executed):
        seen_contexts.append(
            (chain.model_copy(deep=True), list(leads), dict(target), list(executed))
        )
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
            Decision(tool="finish", args={}, reason="自己点検後も結論は同じ"),
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
        "error",  # 早期 finish の自己点検差し戻し
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
            Decision(tool="finish", args={}, reason="再考後も ok"),
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


def test_repeated_identical_call_is_not_reexecuted():
    toolbox = StubToolbox()
    decide = scripted_decider(
        [
            Decision(tool="get_commit", args={"sha": "bbb222"}, reason="1回目"),
            Decision(tool="get_commit", args={"sha": "bbb222"}, reason="2回目(重複)"),
            Decision(tool="finish", args={}, reason="ok"),
            Decision(tool="finish", args={}, reason="再考後も ok"),
        ]
    )
    events = run_dig(toolbox, decide)
    assert toolbox.calls.count("get_commit") == 1  # 2回目はツールを実行しない
    assert any(
        e.type == "error" and "実行済み" in e.payload["message"] for e in events
    )
    assert sum(1 for e in events if e.type == "evidence_found") == 1


def test_failed_call_is_not_retried_with_same_args():
    class FailingToolbox(StubToolbox):
        def blame_line(self, owner, repo, path, line, ref="HEAD"):
            self.calls.append("blame_line")
            raise ValueError(f"line {line} not found in blame ranges for {path}")

    toolbox = FailingToolbox()
    decide = scripted_decider(
        [
            Decision(tool="blame_line", args={"path": "wrong.py", "line": 5}, reason="1回目"),
            Decision(tool="blame_line", args={"path": "wrong.py", "line": 5}, reason="同じ手を再試行"),
            Decision(tool="finish", args={}, reason="ok"),
            Decision(tool="finish", args={}, reason="再考後も ok"),
        ]
    )
    run_dig(toolbox, decide)
    assert toolbox.calls.count("blame_line") == 1  # 失敗した呼び出しも記録され再実行しない


def test_search_issues_yields_leads_for_each_hit():
    decide = scripted_decider(
        [
            Decision(tool="search_issues", args={"query": "inventory v2"}, reason="失効確認"),
            Decision(tool="finish", args={}, reason="ok"),
            Decision(tool="finish", args={}, reason="再考後も ok"),
        ]
    )
    run_dig(StubToolbox(), decide)
    _, second_leads, _, _ = decide.seen[1]
    assert {"tool": "get_issue", "args": {"number": 3}} in second_leads
    assert {"tool": "get_pr", "args": {"number": 4}} in second_leads


def test_decider_receives_executed_history():
    decide = scripted_decider(
        [
            Decision(tool="get_pr", args={"number": 42}, reason="PRを読む"),
            Decision(tool="finish", args={}, reason="ok"),
            Decision(tool="finish", args={}, reason="再考後も ok"),
        ]
    )
    run_dig(StubToolbox(), decide)
    _, _, _, first_executed = decide.seen[0]
    _, _, _, second_executed = decide.seen[1]
    assert first_executed == []
    assert second_executed == [
        {"tool": "get_pr", "args": {"number": 42}, "outcome": "ok"}
    ]


def test_premature_finish_is_rejected_once():
    # 未消化のリードが残ったままの finish は一度だけ差し戻し、再考させる
    decide = scripted_decider(
        [
            Decision(tool="blame_line", args={"path": "src/api.py", "line": 5}, reason="起点"),
            Decision(tool="finish", args={}, reason="もう十分（実は PR 未読）"),
            Decision(tool="finish", args={}, reason="再考したがやはり十分"),
        ]
    )
    events = run_dig(StubToolbox(), decide)
    assert events[-1].type == "done"
    # 差し戻しの事実が LLM の次回コンテキスト（実行履歴）に渡る
    _, _, _, third_executed = decide.seen[2]
    finish_entries = [e for e in third_executed if e["tool"] == "finish"]
    assert len(finish_entries) == 1
    assert finish_entries[0]["outcome"].startswith("rejected:")


def test_finish_after_search_and_empty_leads_is_immediate():
    decide = scripted_decider(
        [
            Decision(tool="blame_line", args={"path": "src/api.py", "line": 5}, reason="起点"),
            Decision(tool="get_commit", args={"sha": "bbb222"}, reason="コミット"),
            Decision(tool="get_pr", args={"number": 42}, reason="PR"),
            Decision(tool="get_issue", args={"number": 12}, reason="Issue"),
            Decision(tool="search_issues", args={"query": "v2"}, reason="失効確認"),
            Decision(tool="get_issue", args={"number": 3}, reason="ヒットを読む"),
            Decision(tool="get_pr", args={"number": 4}, reason="ヒットを読む"),
            Decision(tool="finish", args={}, reason="完全"),
        ]
    )
    events = run_dig(StubToolbox(), decide)
    # リード全消化 + search 済みなら差し戻しなし = 台本どおり8回で終わる
    # （get_pr(4) が参照する Issue #12 は実行済みなのでリードに戻らない）
    assert events[-1].type == "done"
    assert len(decide.seen) == 8


def test_executed_history_records_error_outcome():
    class FailingToolbox(StubToolbox):
        def get_pr(self, owner, repo, number):
            raise ValueError("404 Not Found: PR がありません")

    decide = scripted_decider(
        [
            Decision(tool="get_pr", args={"number": 1}, reason="幻覚"),
            Decision(tool="finish", args={}, reason="ok"),
            Decision(tool="finish", args={}, reason="再考後も ok"),
        ]
    )
    run_dig(FailingToolbox(), decide)
    _, _, _, second_executed = decide.seen[1]
    assert second_executed[0]["outcome"].startswith("error:")
    assert "404" in second_executed[0]["outcome"]


def test_unknown_tool_emits_error_and_continues():
    decide = scripted_decider(
        [
            Decision(tool="warp_drive", args={}, reason="幻覚"),
            Decision(tool="finish", args={}, reason="ok"),
            Decision(tool="finish", args={}, reason="再考後も ok"),
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
            Decision(tool="finish", args={}, reason="再考後も ok"),
        ]
    )
    run_dig(StubToolbox(), decide)
    first_chain, _, first_target, _ = decide.seen[0]
    second_chain, second_leads, _, _ = decide.seen[1]
    assert len(first_chain) == 0
    assert len(second_chain) == 2  # PR 本文 + コメント
    # PR が参照していた Issue #12 が「次の掘り先候補」として提示される
    assert {"tool": "get_issue", "args": {"number": 12}} in second_leads
    # LLM がパスを幻覚しないよう、正確な調査対象を毎回渡す
    assert first_target == {"owner": "o", "repo": "r", "path": "src/api.py", "line": 5}
