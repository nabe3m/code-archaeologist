"""史官（Historian）— 証拠チェーンから最終回答を合成する。

回答は必ず [n] 形式で証拠を引用し、n は EvidenceChain.as_context() の番号に対応。
UI は sources の URL をそのままリンクとして描画する。LLM は generate 関数として注入。
"""

import re
from collections.abc import Callable

from pydantic import BaseModel

from .models import EvidenceChain

_CITATION = re.compile(r"\[(\d+)\]")

_PROMPT_TEMPLATE = """あなたはコードの歴史を語る「史官」です。
以下の発掘済み証拠だけを根拠に、質問へ答えてください。

## 質問
{question}

## 証拠（発掘順・番号は引用用）
{context}

## 回答の要件
- 「いつ・誰が・なぜ・当時の制約・その制約は現在も有効か」の観点で簡潔に
- 主張には必ず対応する証拠番号を [n] 形式で付ける
- 導入・変更・移行の経緯に触れるときは、その変更を行ったコミット・PR と、
  きっかけになった Issue を**それぞれ**引用する（関連する別の証拠で代用しない）
- 対象コード行を導入したコミット（blame / commit の証拠）は、PR を引用していても
  **必ず別途引用する**。コミットが変更の一次記録である
- 証拠にないことは推測と明示するか、書かない
"""


class Source(BaseModel):
    n: int
    label: str
    url: str
    title: str


class Answer(BaseModel):
    text: str
    sources: list[Source]


class Historian:
    def __init__(self, generate: Callable[[str], str]) -> None:
        self._generate = generate

    def narrate(self, question: str, chain: EvidenceChain) -> Answer:
        if not chain.items:
            # 証拠ゼロで LLM に回答させると存在しない引用を捏造するため、正直に返す
            return Answer(
                text="調査しましたが、この質問に答えられる証拠が見つかりませんでした。"
                "対象のファイルパス・行番号が正しいか確認してください。",
                sources=[],
            )
        prompt = _PROMPT_TEMPLATE.format(question=question, context=chain.as_context())
        text = self._generate(prompt)
        cited = sorted({int(n) for n in _CITATION.findall(text)})
        sources = [
            Source(n=n, label=chain.items[n - 1].label(), url=chain.items[n - 1].url,
                   title=chain.items[n - 1].title)
            for n in cited
            if 1 <= n <= len(chain.items)
        ]
        return Answer(text=text, sources=sources)
