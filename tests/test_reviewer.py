"""レビュー officer: PR で消されようとしている防御的コードを、消される前に止める。

監査官と違い、人が質問しなくても pull_request で発火する。判定経路
（発掘 → 失効確認の強制実行 → 判決）は Auditor.investigate をそのまま共有する。
"""

from code_archaeologist.auditor import Auditor, Candidate, Verdict
from code_archaeologist.github_tools import PrDiff, PrFile
from code_archaeologist.models import DigEvent, Evidence, EvidenceChain, Prophecy
from code_archaeologist.reviewer import PrReviewer, removed_lines

BASE_SHA = "base1234"

# 決済リトライ(#9: レート制限は増枠予定なし)を丸ごと削除する PR の差分。
PATCH = """@@ -20,10 +20,3 @@ def capture_payment(order, payments):
     \"\"\"注文金額を決済する。\"\"\"
-    # payment API はレート制限 (60 req/min) があり 429 を返す (#9)
-    for attempt in range(3):
-        try:
-            return payments.capture(order["id"], order["amount"])
-        except RateLimitedError:
-            if attempt == 2:
-                raise
-            time.sleep(2 ** attempt)
-    raise RuntimeError("unreachable")
+    return payments.capture(order["id"], order["amount"])
"""

BASE_CODE = "".join(f"line {i}\n" for i in range(1, 40))


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
    def __init__(self, patch=PATCH):
        self.calls = []
        self.comments = []
        self._patch = patch

    def get_pr_diff(self, owner, repo, number):
        self.calls.append(f"get_pr_diff({number})")
        return PrDiff(
            base_sha=BASE_SHA, files=[PrFile(path="orders/api.py", patch=self._patch)]
        )

    def get_file(self, owner, repo, path, ref="HEAD"):
        self.calls.append(f"get_file({path}@{ref})")
        return BASE_CODE

    def search_issues(self, owner, repo, query):
        self.calls.append(f"search_issues({query})")
        return [
            {"number": 10, "title": "決済リトライ追加", "is_pr": True, "state": "closed",
             "url": "https://github.com/o/r/pull/10"},
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

    def post_pr_comment(self, owner, repo, number, body):
        self.calls.append(f"post_pr_comment({number})")
        self.comments.append(body)
        return {"url": f"https://github.com/o/r/pull/{number}#issuecomment-7"}


def stub_dig(owner, repo, path, line, question):
    chain = EvidenceChain()
    chain.add(ev("commit", "abc1234", url="https://github.com/o/r/commit/abc1234"))
    yield DigEvent(type="dig_started", payload={"question": question, "target": {}})
    yield DigEvent(
        type="done",
        payload={"steps": 1, "evidence_count": 1, "stopped_by": "finish",
                 "chain": chain.model_dump()},
    )


def stub_prophesy(candidate, verdict, chain):
    return Prophecy(
        guarded_incident="プロバイダのレート制限 60 req/min で 429 が出た [1]",
        recurrence_symptoms="ピーク時の決済が 429 で失敗しはじめる",
        rollback_hint="この PR を revert して指数バックオフを戻す",
    )


def make_reviewer(toolbox, expired=False, candidate_line=22, prophesy=stub_prophesy):
    def find_candidates(path, code):
        return [
            Candidate(line=candidate_line, snippet="for attempt in range(3)",
                      reason="リトライは歴史的事情がありそう"),
        ]

    auditor = Auditor(
        toolbox=toolbox,
        dig=stub_dig,
        find_candidates=find_candidates,
        forward_query=lambda chain: "payment rate limit",
        judge=lambda c, chain, code: Verdict(
            expired=expired,
            justification=("v2 で解消済み [1]" if expired
                           else "レート制限は増枠予定なしで制約は現在も有効 [1][2]"),
            lines_to_remove=[22] if expired else [],
        ),
        prophesy=prophesy,
    )
    return PrReviewer(
        toolbox=toolbox,
        investigate=auditor.investigate,
        find_candidates=find_candidates,
        prophesy=prophesy,
    )


# --- diff パース ---------------------------------------------------------


def test_removed_lines_uses_base_side_numbering():
    assert removed_lines(PATCH) == set(range(21, 30))


def test_added_lines_do_not_advance_base_numbering():
    patch = "@@ -5,2 +5,4 @@\n+added a\n+added b\n-removed\n context\n"
    assert removed_lines(patch) == {5}


def test_multiple_hunks_are_tracked_independently():
    patch = "@@ -1,2 +1,1 @@\n-a\n b\n@@ -50,2 +49,1 @@\n-c\n d\n"
    assert removed_lines(patch) == {1, 50}


def test_patch_without_removals_yields_nothing():
    assert removed_lines("@@ -1,0 +1,2 @@\n+new\n+new2\n") == set()


# --- レビュー本体 ---------------------------------------------------------


def test_still_valid_code_being_deleted_produces_warning_comment():
    """auditor.py の「expired=False のとき何も成果物が出ない」穴を埋める中核。"""
    toolbox = StubToolbox()
    events = list(make_reviewer(toolbox, expired=False).review("o", "r", 42))

    assert "post_pr_comment(42)" in toolbox.calls
    body = toolbox.comments[0]
    assert "🚨" in body
    assert "この削除は危険です" in body
    assert "増枠予定なし" in body  # 判定理由
    assert "429" in body  # Oracle が語る「守っているもの」
    # 証拠が URL 付きで引用される
    assert "https://github.com/o/r/commit/abc1234" in body
    assert "https://github.com/o/r/pull/10" in body

    finding = [e for e in events if e.type == "review_finding"][0]
    assert finding.payload["verdict"]["expired"] is False
    assert finding.payload["comment_url"].endswith("#issuecomment-7")


def test_expired_code_being_deleted_produces_approval_comment():
    toolbox = StubToolbox()
    list(make_reviewer(toolbox, expired=True).review("o", "r", 42))
    body = toolbox.comments[0]
    assert "✅" in body
    assert "歴史的に妥当" in body
    assert "🚨" not in body


def test_only_candidates_inside_the_deleted_range_are_investigated():
    """PR が触っていない防御的コードは対象外（レビューを騒がしくしない）。"""
    toolbox = StubToolbox()
    events = list(make_reviewer(toolbox, candidate_line=3).review("o", "r", 42))
    assert not toolbox.comments
    assert all(e.type != "review_finding" for e in events)
    assert not any(c.startswith("search_issues") for c in toolbox.calls)


def test_investigation_runs_against_the_base_sha_not_head():
    """PR ブランチには既にその行が無いので、base 側を掘らないと何も出ない。"""
    toolbox = StubToolbox()
    list(make_reviewer(toolbox).review("o", "r", 42))
    assert f"get_file(orders/api.py@{BASE_SHA})" in toolbox.calls


def test_forward_check_is_forced_before_judging():
    toolbox = StubToolbox()
    list(make_reviewer(toolbox).review("o", "r", 42))
    assert "search_issues(payment rate limit)" in toolbox.calls
    assert "get_pr(10)" in toolbox.calls


def test_comment_failure_degrades_to_error_event():
    toolbox = StubToolbox()

    def boom(owner, repo, number, body):
        raise RuntimeError("403")

    toolbox.post_pr_comment = boom
    events = list(make_reviewer(toolbox).review("o", "r", 42))
    assert any(e.type == "error" and "403" in e.payload["message"] for e in events)
    # 判定結果そのものは失われない
    assert any(e.type == "review_finding" for e in events)


def test_oracle_stays_silent_without_evidence():
    toolbox = StubToolbox()
    toolbox.search_issues = lambda owner, repo, query: []
    called = []

    def spy(candidate, verdict, chain):
        called.append(True)
        return stub_prophesy(candidate, verdict, chain)

    reviewer = make_reviewer(toolbox, prophesy=spy)

    def empty_dig(owner, repo, path, line, question):
        yield DigEvent(
            type="done",
            payload={"steps": 0, "evidence_count": 0, "stopped_by": "finish",
                     "chain": EvidenceChain().model_dump()},
        )

    reviewer._investigate.__self__._dig = empty_dig
    list(reviewer.review("o", "r", 42))
    assert not called
    assert "この行が守っているもの" not in toolbox.comments[0]


def test_files_without_removals_are_skipped_entirely():
    toolbox = StubToolbox(patch="@@ -1,0 +1,1 @@\n+only additions\n")
    events = list(make_reviewer(toolbox).review("o", "r", 42))
    assert not any(c.startswith("get_file") for c in toolbox.calls)
    assert events == []
