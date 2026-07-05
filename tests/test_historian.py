"""史官: 証拠チェーンから出典リンク付きの最終回答を合成する。LLM は注入。"""

from code_archaeologist.historian import Historian
from code_archaeologist.models import Evidence, EvidenceChain


def build_chain():
    chain = EvidenceChain()
    chain.add(
        Evidence(
            kind="commit",
            ref="bbb222",
            url="https://github.com/o/r/commit/bbb222",
            title="fix: sleep(3) to avoid race (#42)",
            detail="Upstream API returns before write is visible.",
            author="alice",
            date="2019-03-01",
        )
    )
    chain.add(
        Evidence(
            kind="issue",
            ref="12",
            url="https://github.com/o/r/issues/12",
            title="CI flaky: read-after-write fails",
            author="dave",
            date="2019-02-01",
        )
    )
    return chain


def capture_prompt_llm(response: str):
    prompts = []

    def generate(prompt: str) -> str:
        prompts.append(prompt)
        return response

    generate.prompts = prompts
    return generate


def test_prompt_contains_question_and_numbered_evidence():
    generate = capture_prompt_llm("回答 [1][2]")
    Historian(generate).narrate("なぜ sleep(3) があるの?", build_chain())
    prompt = generate.prompts[0]
    assert "なぜ sleep(3) があるの?" in prompt
    assert "[1] commit bbb222" in prompt
    assert "[2] issue #12" in prompt


def test_answer_carries_text_and_cited_sources():
    generate = capture_prompt_llm("sleep(3) は 2019 年の上流 API 遅延対策 [1]。元報告は [2]。")
    answer = Historian(generate).narrate("なぜ?", build_chain())
    assert "[1]" in answer.text
    assert len(answer.sources) == 2
    assert answer.sources[0].n == 1
    assert answer.sources[0].url == "https://github.com/o/r/commit/bbb222"
    assert answer.sources[1].label == "issue #12"


def test_empty_chain_returns_honest_no_evidence_answer_without_calling_llm():
    generate = capture_prompt_llm("呼ばれてはいけない")
    answer = Historian(generate).narrate("なぜ?", EvidenceChain())
    assert generate.prompts == []  # 証拠ゼロで LLM に回答させると引用を捏造する
    assert answer.sources == []
    assert "証拠" in answer.text and "見つかりません" in answer.text


def test_sources_only_include_cited_numbers():
    generate = capture_prompt_llm("答えは [2] だけを引用する。")
    answer = Historian(generate).narrate("なぜ?", build_chain())
    assert [s.n for s in answer.sources] == [2]
