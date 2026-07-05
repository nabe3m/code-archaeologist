"""証拠チェーンと構造化イベント: 調査官・史官・UI(SSE) の共通語彙。"""

from code_archaeologist.models import DigEvent, Evidence, EvidenceChain


def make_evidence(**overrides):
    defaults = dict(
        kind="commit",
        ref="abc1234",
        url="https://github.com/o/r/commit/abc1234",
        title="fix: add sleep to avoid race",
        detail="Adds sleep(3) as workaround for flaky upstream API",
        author="alice",
        date="2019-03-01",
    )
    return Evidence(**{**defaults, **overrides})


def test_chain_deduplicates_by_url():
    chain = EvidenceChain()
    chain.add(make_evidence())
    chain.add(make_evidence(title="duplicate with different title"))
    assert len(chain) == 1


def test_chain_renders_numbered_context():
    chain = EvidenceChain()
    chain.add(make_evidence())
    chain.add(
        make_evidence(
            kind="pull_request",
            ref="42",
            url="https://github.com/o/r/pull/42",
            title="Workaround for upstream flakiness",
        )
    )
    context = chain.as_context()
    assert "[1] commit abc1234" in context
    assert "[2] pull_request #42" in context
    assert "https://github.com/o/r/pull/42" in context


def test_dig_event_serializes_for_sse():
    event = DigEvent(
        type="dig_decision",
        payload={"reason": "コミットメッセージが PR #42 を参照", "next": "get_pr"},
    )
    data = event.model_dump()
    assert data["type"] == "dig_decision"
    assert data["payload"]["next"] == "get_pr"
