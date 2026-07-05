"""Gemini アダプタ — コアに注入する decide / generate の本番実装。

- 調査官の判断: Flash 系（多数回呼ぶ・低コスト）。structured output で Decision を得る
- 史官の回答: 上位モデル（1回だけ・品質勝負）
モデルは環境変数で差し替え可能。Vertex AI へは Client 初期化の切替のみで移行できる。
"""

import os
import time
from typing import Literal

from google import genai
from google.genai import errors
from pydantic import BaseModel

from .excavator import Decision
from .models import EvidenceChain

EXCAVATOR_MODEL = os.environ.get("EXCAVATOR_MODEL", "gemini-2.5-flash")
HISTORIAN_MODEL = os.environ.get("HISTORIAN_MODEL", "gemini-2.5-pro")

_DECIDE_PROMPT = """あなたはコードの歴史を発掘する「調査官」です。
質問に答えるための証拠を GitHub から遡行収集しています。
次の一手を決めてください。

## 質問
{question}

## これまでに発掘した証拠
{context}

## 次の掘り先候補（機械的に抽出したもの。従う義務はない）
{leads}

## 使える道具
- blame_line(path: str, line: int): その行を最後に変更したコミットを特定（遡行の起点）
- get_commit(sha: str): コミット全文と紐づく PR 番号
- get_pr(number: int): PR 本文・議論・参照 Issue 番号
- get_issue(number: int): Issue 本文とコメント
- finish(): 質問に答えるのに十分な証拠が揃ったら調査終了

## 判断基準
- 証拠が空なら、まず blame_line で起点を作る
- 「なぜ」に直結する一次情報（PR 議論・Issue）を優先して掘る
- 同じ場所を二度掘らない。十分に揃ったら潔く finish
- reason には「何を根拠に、なぜそこを掘るのか」を日本語で1文で書く（ユーザーに表示される）
"""


class _DecisionArgs(BaseModel):
    """Gemini structured output 用の型付き引数。

    Developer API は additionalProperties（自由 dict）非対応のため、
    全ツールの引数を optional なフラット構造で受けて Decision.args に詰め直す。
    """

    path: str | None = None
    line: int | None = None
    sha: str | None = None
    number: int | None = None


class _LlmDecision(BaseModel):
    tool: Literal["blame_line", "get_commit", "get_pr", "get_issue", "finish"]
    args: _DecisionArgs
    reason: str


def _with_quota_backoff(call, attempts: int = 4):
    """429（無料枠は 5 req/min）でもデモを止めないためのバックオフ。"""
    for i in range(attempts):
        try:
            return call()
        except errors.ClientError as exc:
            if exc.code != 429 or i == attempts - 1:
                raise
            time.sleep(15 * (i + 1))
    raise RuntimeError("unreachable")


class GeminiAgents:
    def __init__(self, api_key: str | None = None) -> None:
        self._client = genai.Client(api_key=api_key or os.environ["GEMINI_API_KEY"])

    def decide(self, question: str, chain: EvidenceChain, leads: list[dict]) -> Decision:
        prompt = _DECIDE_PROMPT.format(
            question=question,
            context=chain.as_context() or "（まだ何もない）",
            leads=leads or "（なし）",
        )
        response = _with_quota_backoff(
            lambda: self._client.models.generate_content(
                model=EXCAVATOR_MODEL,
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "response_schema": _LlmDecision,
                },
            )
        )
        parsed: _LlmDecision = response.parsed
        return Decision(
            tool=parsed.tool,
            args=parsed.args.model_dump(exclude_none=True),
            reason=parsed.reason,
        )

    def generate(self, prompt: str) -> str:
        response = _with_quota_backoff(
            lambda: self._client.models.generate_content(
                model=HISTORIAN_MODEL, contents=prompt
            )
        )
        return response.text or ""
