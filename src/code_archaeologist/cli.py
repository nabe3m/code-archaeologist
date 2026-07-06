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
    "audit_candidate": "🔎",
    "verdict": "⚖️",
    "pr_created": "🎉",
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


def main_audit() -> None:
    """監査官 CLI: 失効した防御的コードを検出し、削除 PR を実作成する。"""
    load_dotenv()
    parser = argparse.ArgumentParser(description="Code Archaeologist Auditor CLI")
    parser.add_argument("repo", help="owner/name 形式")
    parser.add_argument("path", help="監査対象ファイルパス")
    args = parser.parse_args()

    for var in ("GEMINI_API_KEY", "GITHUB_TOKEN"):
        if not os.environ.get(var):
            sys.exit(f"環境変数 {var} が未設定です（.env を確認してください）")

    from .auditor import Auditor

    owner, repo = args.repo.split("/", 1)
    agents = GeminiAgents()
    toolbox = GitHubToolbox(token=os.environ["GITHUB_TOKEN"])
    excavator = Excavator(toolbox=toolbox, decide=agents.decide)
    auditor = Auditor(
        toolbox=toolbox,
        dig=excavator.dig,
        find_candidates=agents.find_candidates,
        forward_query=agents.forward_query,
        judge=agents.judge,
    )

    for event in auditor.audit(owner, repo, args.path):
        icon = ICONS.get(event.type, "·")
        p = event.payload
        match event.type:
            case "audit_candidate":
                print(f"{icon} 監査候補: L{p['line']} `{p['snippet']}` — {p['reason']}")
            case "dig_started":
                print(f"{icon} 発掘開始: {p['question']}")
            case "dig_decision":
                print(f"{icon} {p['reason']}  →  {p['tool']}({p['args']})")
            case "evidence_found":
                e = p["evidence"]
                print(f"{icon} 発掘: {e['kind']} {e['ref']} — {e['title']}")
            case "error":
                print(f"{icon} {p['message']}")
            case "done":
                print(f"{icon} 発掘完了: 証拠 {p['evidence_count']} 件")
            case "verdict":
                status = "失効 → 削除 PR を作成します" if p["expired"] else "現在も有効"
                print(f"{icon} 判決: {status}\n   {p['justification']}")
            case "pr_created":
                print(f"{icon} 削除 PR を作成しました: {p['url']}")


if __name__ == "__main__":
    main()
