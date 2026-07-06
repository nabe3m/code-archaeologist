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

## 調査対象（この値を一字一句そのまま使うこと。パスや行番号を創作・変形しない）
- リポジトリ: {owner}/{repo}
- ファイル: {path}
- 行番号: {line}

## これまでに発掘した証拠
{context}

## 実行済みの呼び出しと結果（同じ呼び出しを繰り返さない。error は引数が間違っていた可能性が高い）
{executed}

## 次の掘り先候補（API から機械抽出した正確な番号。原則ここから選ぶ）
{leads}

## 使える道具
- blame_line(path: str, line: int): その行を最後に変更したコミットを特定（遡行の起点）
- get_commit(sha: str): コミット全文と紐づく PR 番号
- get_pr(number: int): PR 本文・議論・参照 Issue 番号
- get_issue(number: int): Issue 本文とコメント
- search_issues(query: str): リポジトリ内の Issue/PR をキーワード検索（制約がその後解消されたかの前方調査に使う）
- finish(): 質問に答えるのに十分な証拠が揃ったら調査終了

## 進め方（上から順に守ること）
1. 証拠が空なら blame_line で起点を作る
2. コミットを見つけたら**コミットメッセージだけで満足せず**、紐づく PR（掘り先候補の get_pr）とその議論・参照 Issue を必ず読む。「なぜ」の一次情報はコミットではなく PR 議論と Issue にある
3. 質問に「今も必要か・有効か・消せるか」が含まれる場合、**finish の前に必ず search_issues で当時の制約のその後**（解消・バージョン移行・EOL 等）を調べ、ヒットした Issue/PR も読む（例: query="inventory v2"）
4. finish してよいのは「質問のすべての部分に証拠番号付きで答えられる」ときだけ。答えられない部分があるのに未消化の掘り先候補や search_issues が残っているなら、先にそれを実行する

## 注意
- 掘り先候補は API から機械抽出した確実な番号。**コミットメッセージ中の「#N」は Issue のことも多く、PR 番号として信用しない**
- エラーになった呼び出しを同じ引数で繰り返さない
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


_RETRYABLE = {429, 500, 503, 504}  # 無料枠クォータ / 一時的な高負荷


def _with_quota_backoff(call, attempts: int = 4):
    """429/5xx でもデモを止めないためのバックオフ。"""
    for i in range(attempts):
        try:
            return call()
        except errors.APIError as exc:
            if exc.code not in _RETRYABLE or i == attempts - 1:
                raise
            time.sleep(15 * (i + 1))
    raise RuntimeError("unreachable")


class GeminiAgents:
    def __init__(self, api_key: str | None = None) -> None:
        self._client = genai.Client(api_key=api_key or os.environ["GEMINI_API_KEY"])

    def decide(
        self,
        question: str,
        chain: EvidenceChain,
        leads: list[dict],
        target: dict,
        executed: list[dict],
    ) -> Decision:
        def render_call(tool: str, args: dict) -> str:
            rendered_args = ", ".join(f"{k}={v!r}" for k, v in args.items())
            return f"{tool}({rendered_args})"

        leads_text = "\n".join(
            f"- {render_call(lead['tool'], lead['args'])}" for lead in leads
        )
        executed_text = "\n".join(
            f"- {render_call(e['tool'], e['args'])} → {e.get('outcome', 'ok')}"
            for e in executed
        )
        prompt = _DECIDE_PROMPT.format(
            question=question,
            context=chain.as_context() or "（まだ何もない）",
            leads=leads_text or "（なし。search_issues で新しい手がかりを探すか finish）",
            executed=executed_text or "（なし）",
            **target,
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
