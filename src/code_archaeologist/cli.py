"""CLI — Day 1 の E2E 確認用。遡行イベントを流しながら最終回答を表示する。

usage: uv run archaeologist owner/repo path/to/file.py 42 "なぜこの行があるの?"
"""

import argparse
import os
import sys

from dotenv import load_dotenv

from .excavator import Excavator
from .github_tools import GitHubToolbox
from .historian import Historian
from .llm import GeminiAgents
from .models import EvidenceChain

ICONS = {
    "dig_started": "🏺",
    "dig_decision": "🤔",
    "evidence_found": "📜",
    "error": "⚠️",
    "done": "⛏️",
}


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Code Archaeologist CLI")
    parser.add_argument("repo", help="owner/name 形式")
    parser.add_argument("path", help="対象ファイルパス")
    parser.add_argument("line", type=int, help="対象行番号")
    parser.add_argument("question", help="コードへの質問")
    parser.add_argument("--max-steps", type=int, default=12)
    args = parser.parse_args()

    for var in ("GEMINI_API_KEY", "GITHUB_TOKEN"):
        if not os.environ.get(var):
            sys.exit(f"環境変数 {var} が未設定です（.env を確認してください）")

    owner, repo = args.repo.split("/", 1)
    agents = GeminiAgents()
    excavator = Excavator(
        toolbox=GitHubToolbox(token=os.environ["GITHUB_TOKEN"]),
        decide=agents.decide,
        max_steps=args.max_steps,
    )

    chain = EvidenceChain()
    for event in excavator.dig(owner, repo, args.path, args.line, args.question):
        icon = ICONS.get(event.type, "·")
        p = event.payload
        match event.type:
            case "dig_started":
                print(f"{icon} 調査開始: {p['question']}")
            case "dig_decision":
                print(f"{icon} {p['reason']}  →  {p['tool']}({p['args']})")
            case "evidence_found":
                e = p["evidence"]
                print(f"{icon} 発掘: {e['kind']} {e['ref']} — {e['title']}")
            case "error":
                print(f"{icon} {p['message']}")
            case "done":
                chain = EvidenceChain.model_validate(p["chain"])
                print(f"{icon} 調査完了: {p['steps']} steps, 証拠 {p['evidence_count']} 件")

    print("\n" + "=" * 60)
    answer = Historian(agents.generate).narrate(args.question, chain)
    print(answer.text)
    print("\n出典:")
    for s in answer.sources:
        print(f"  [{s.n}] {s.label} — {s.title}\n      {s.url}")


if __name__ == "__main__":
    main()
