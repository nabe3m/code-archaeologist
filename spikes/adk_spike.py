"""ADK スパイク — 検証項目:

1. ADK のイベントストリームから「遡行の各判断 + その理由」を構造化イベントとして
   取り出せるか（UI のタイムライン表示に必須）
2. ツール呼び出しループ（blame → commit → PR → issue）が自律的に回るか
3. 自前ループ（実装済み・テスト済み）と比べた複雑さ

実行: uv run --with google-adk python spikes/adk_spike.py
判断結果は README のアーキテクチャ節に記録する。
"""

import asyncio
import os

from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault("GOOGLE_API_KEY", os.environ.get("GEMINI_API_KEY", ""))

from google.adk.agents import Agent  # noqa: E402
from google.adk.runners import InMemoryRunner  # noqa: E402
from google.genai import types  # noqa: E402

CALLS: list[str] = []


def blame_line(path: str, line: int) -> dict:
    """指定行を最後に変更したコミットを特定する（遡行の起点）。"""
    CALLS.append(f"blame_line({path}, {line})")
    return {
        "sha": "bbb222",
        "message": "fix: sleep(3) to avoid race (#42)",
        "author": "alice",
        "date": "2019-03-01",
    }


def get_commit(sha: str) -> dict:
    """コミット全文と紐づく PR 番号を取得する。"""
    CALLS.append(f"get_commit({sha})")
    return {
        "sha": sha,
        "message": "fix: sleep(3) to avoid race (#42)\n\nUpstream API returns before write is visible.",
        "pr_numbers": [42],
    }


def get_pr(number: int) -> dict:
    """PR 本文・議論・参照 Issue 番号を取得する。"""
    CALLS.append(f"get_pr({number})")
    return {
        "number": number,
        "title": "Workaround for upstream flakiness",
        "body": "Fixes #12 — upstream eventual consistency breaks CI.",
        "referenced_issues": [12],
    }


def get_issue(number: int) -> dict:
    """Issue 本文とコメントを取得する。"""
    CALLS.append(f"get_issue({number})")
    return {
        "number": number,
        "title": "CI flaky: read-after-write fails",
        "body": "Upstream API is eventually consistent",
    }


agent = Agent(
    name="excavator",
    model="gemini-2.5-flash",
    instruction=(
        "あなたはコードの歴史を発掘する調査官。質問に答える証拠が揃うまで"
        "blame_line → get_commit → get_pr → get_issue と自律的に遡行する。"
        "各ツール呼び出しの前に、なぜそこを掘るのか理由を1文で説明せよ。"
    ),
    tools=[blame_line, get_commit, get_pr, get_issue],
)


async def main() -> None:
    runner = InMemoryRunner(agent=agent)
    session = await runner.session_service.create_session(
        app_name=runner.app_name, user_id="spike"
    )
    message = types.Content(
        role="user",
        parts=[types.Part(text="src/api.py の 5 行目に sleep(3) があるのはなぜ?")],
    )
    print("=== ADK event stream ===")
    async for event in runner.run_async(
        user_id="spike", session_id=session.id, new_message=message
    ):
        author = getattr(event, "author", "?")
        if event.content:
            for part in event.content.parts or []:
                if part.function_call:
                    print(f"[{author}] TOOL_CALL {part.function_call.name}({dict(part.function_call.args)})")
                elif part.function_response:
                    print(f"[{author}] TOOL_RESULT {part.function_response.name}")
                elif part.text:
                    print(f"[{author}] TEXT {part.text[:120]!r}")
    print("\n=== tool call order ===")
    print("\n".join(CALLS))


if __name__ == "__main__":
    asyncio.run(main())
