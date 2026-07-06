"""監査官: 理由が失効した防御的コードを検出し、証拠付き削除 PR を作成する。

LLM（候補検出・前方クエリ生成・判決）と発掘（dig）は注入。
失効確認の search_issues は LLM 任せにせず監査官が決め打ちで実行する。
"""

from code_archaeologist.auditor import Auditor, Candidate, Verdict
from code_archaeologist.models import DigEvent, Evidence, EvidenceChain

CODE = "import time\n\n# workaround (#1)\ntime.sleep(3)\nprint('done')\n"


def ev(kind, ref, url=None, **overrides):
    defaults = dict(
        url=url or f"https://github.com/o/r/{kind}/{ref}",
        title=f"{kind} {ref} title",
        detail="detail",
        author="alice",
        date="2024-03-18",
    )
    return Evidence(kind=kind, ref=str(ref), **{**defaults, **overrides})


class StubToolbox:
    def __init__(self):
        self.calls = []
        self.deletion_pr_kwargs = None

    def get_file(self, owner, repo, path, ref="HEAD"):
        self.calls.append("get_file")
        return CODE

    def search_issues(self, owner, repo, query):
        self.calls.append(f"search_issues({query})")
        return [
            {"number": 4, "title": "v2 へ移行", "is_pr": True, "state": "closed",
             "url": "https://github.com/o/r/pull/4"},
        ]

    def get_pr(self, owner, repo, number):
        from code_archaeologist.github_tools import PrResult

        self.calls.append(f"get_pr({number})")
        return PrResult(
            evidence=ev("pull_request", number, url=f"https://github.com/o/r/pull/{number}"),
            comments=[],
            referenced_issues=[],
        )

    def get_issue(self, owner, repo, number):
        from code_archaeologist.github_tools import IssueResult

        self.calls.append(f"get_issue({number})")
        return IssueResult(evidence=ev("issue", number), comments=[])

    def create_deletion_pr(self, owner, repo, **kwargs):
        self.calls.append("create_deletion_pr")
        self.deletion_pr_kwargs = kwargs
        return {"number": 9, "url": "https://github.com/o/r/pull/9"}


def stub_dig(owner, repo, path, line, question):
    """発掘の代役: blame 証拠1件 → done(chain) を流す。"""
    chain = EvidenceChain()
    chain.add(ev("commit", "e536eff", url="https://github.com/o/r/commit/e536eff"))
    yield DigEvent(type="dig_started", payload={"question": question, "target": {}})
    yield DigEvent(type="evidence_found", payload={"evidence": chain.items[0].model_dump()})
    yield DigEvent(
        type="done",
        payload={"steps": 1, "evidence_count": 1, "stopped_by": "finish",
                 "chain": chain.model_dump()},
    )


def make_auditor(toolbox, expired=True):
    judged_chains = []

    def find_candidates(path, code):
        return [Candidate(line=4, snippet="time.sleep(3)", reason="歴史的事情がありそうな待機")]

    def forward_query(chain):
        return "inventory v2"

    def judge(candidate, chain, code):
        judged_chains.append(chain.model_copy(deep=True))
        return Verdict(
            expired=expired,
            justification="v2 移行済みのため失効 [1][2]" if expired else "まだ有効",
            lines_to_remove=[3, 4] if expired else [],
        )

    auditor = Auditor(
        toolbox=toolbox,
        dig=stub_dig,
        find_candidates=find_candidates,
        forward_query=forward_query,
        judge=judge,
    )
    auditor._judged_chains = judged_chains
    return auditor


def test_expired_code_produces_deletion_pr_with_cited_evidence():
    toolbox = StubToolbox()
    events = list(make_auditor(toolbox).audit("o", "r", "orders/api.py"))
    types = [e.type for e in events]
    assert "audit_candidate" in types
    assert "verdict" in types
    assert types[-1] == "pr_created"
    assert events[-1].payload["url"] == "https://github.com/o/r/pull/9"
    # 削除 PR は正しい行を消し、本文に証拠 URL を引用する
    kwargs = toolbox.deletion_pr_kwargs
    assert kwargs["lines"] == [3, 4]
    assert "https://github.com/o/r/commit/e536eff" in kwargs["body"]
    assert "https://github.com/o/r/pull/4" in kwargs["body"]


def test_forward_check_runs_search_and_digs_hits_before_judging():
    toolbox = StubToolbox()
    auditor = make_auditor(toolbox)
    list(auditor.audit("o", "r", "orders/api.py"))
    assert "search_issues(inventory v2)" in toolbox.calls
    assert "get_pr(4)" in toolbox.calls
    # 判決時のチェーンには前方調査で得た PR #4 の証拠も含まれている
    judged = auditor._judged_chains[0]
    assert any(e.kind == "pull_request" and e.ref == "4" for e in judged.items)


def test_valid_code_creates_no_pr():
    toolbox = StubToolbox()
    events = list(make_auditor(toolbox, expired=False).audit("o", "r", "orders/api.py"))
    assert "create_deletion_pr" not in toolbox.calls
    verdicts = [e for e in events if e.type == "verdict"]
    assert verdicts[0].payload["expired"] is False
    assert all(e.type != "pr_created" for e in events)
