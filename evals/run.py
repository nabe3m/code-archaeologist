"""考古学クイズの採点スクリプト。

各質問を調査官+史官に通し、回答の出典に期待する一次資料（URL 部分一致）が
すべて含まれるかで採点する。LLM の文言ゆらぎに依存しない。

usage: uv run python evals/run.py [--id why-sleep]
"""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from code_archaeologist.excavator import Excavator
from code_archaeologist.github_tools import GitHubToolbox
from code_archaeologist.historian import Historian
from code_archaeologist.llm import GeminiAgents
from code_archaeologist.models import EvidenceChain


def run_question(agents: GeminiAgents, toolbox: GitHubToolbox, q: dict) -> dict:
    owner, repo = q["repo"].split("/", 1)
    excavator = Excavator(toolbox=toolbox, decide=agents.decide)
    chain = EvidenceChain()
    steps = 0
    for event in excavator.dig(owner, repo, q["path"], q["line"], q["question"]):
        if event.type == "done":
            chain = EvidenceChain.model_validate(event.payload["chain"])
            steps = event.payload["steps"]
    answer = Historian(agents.generate).narrate(q["question"], chain)
    cited_urls = [s.url for s in answer.sources]
    missing = [
        expected
        for expected in q["expected_sources"]
        if not any(expected in url for url in cited_urls)
    ]
    return {
        "id": q["id"],
        "passed": not missing,
        "steps": steps,
        "evidence": len(chain),
        "cited": cited_urls,
        "missing": missing,
    }


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", help="この ID の質問だけ実行する")
    args = parser.parse_args()

    for var in ("GEMINI_API_KEY", "GITHUB_TOKEN"):
        if not os.environ.get(var):
            sys.exit(f"環境変数 {var} が未設定です")

    spec = json.loads((Path(__file__).parent / "questions.json").read_text())
    questions = [q for q in spec["questions"] if not args.id or q["id"] == args.id]

    agents = GeminiAgents()
    toolbox = GitHubToolbox(token=os.environ["GITHUB_TOKEN"])
    results = []
    for q in questions:
        print(f"▶ {q['id']}: {q['question']}")
        try:
            result = run_question(agents, toolbox, q)
        except Exception as exc:
            result = {"id": q["id"], "passed": False, "missing": [f"(error: {exc})"],
                      "steps": 0, "evidence": 0, "cited": []}
        mark = "✅" if result["passed"] else "❌"
        print(f"  {mark} steps={result['steps']} evidence={result['evidence']}")
        if result["missing"]:
            print(f"     未引用の期待出典: {result['missing']}")
        results.append(result)

    passed = sum(1 for r in results if r["passed"])
    print(f"\n== {passed}/{len(results)} passed ==")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
