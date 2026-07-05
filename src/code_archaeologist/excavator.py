"""調査官（Excavator）— 遡行ループの心臓部。

各ステップの「次にどこを掘るか」は注入された decide 関数（本番では LLM）が
自律判断する。固定パイプラインではない。ループ自体は決定的で、
判断・発見・終了をすべて構造化イベント（DigEvent）として発行する。
UI(SSE)・構造化ログ・デモ動画の素材はすべてこのイベント列から作る。
"""

from collections.abc import Callable, Iterator

from pydantic import BaseModel

from .models import DigEvent, Evidence, EvidenceChain


class Decision(BaseModel):
    tool: str  # blame_line / get_commit / get_pr / get_issue / finish
    args: dict
    reason: str


DecideFn = Callable[[str, EvidenceChain, list[dict]], Decision]


class Excavator:
    def __init__(self, toolbox, decide: DecideFn, max_steps: int = 12) -> None:
        self._toolbox = toolbox
        self._decide = decide
        self._max_steps = max_steps

    def dig(
        self, owner: str, repo: str, path: str, line: int, question: str
    ) -> Iterator[DigEvent]:
        chain = EvidenceChain()
        leads: list[dict] = [{"tool": "blame_line", "args": {"path": path, "line": line}}]
        stopped_by = "finish"

        yield DigEvent(
            type="dig_started",
            payload={
                "question": question,
                "target": {"owner": owner, "repo": repo, "path": path, "line": line},
            },
        )

        steps = 0
        while True:
            if steps >= self._max_steps:
                stopped_by = "max_steps"
                break
            decision = self._decide(question, chain, leads)
            steps += 1
            yield DigEvent(
                type="dig_decision",
                payload={"tool": decision.tool, "args": decision.args, "reason": decision.reason},
            )
            if decision.tool == "finish":
                break

            try:
                found, new_leads = self._execute(owner, repo, decision)
            except Exception as exc:  # 幻覚ツール名や API エラーでもループは止めない
                yield DigEvent(
                    type="error",
                    payload={"tool": decision.tool, "message": str(exc)},
                )
                continue

            leads = [l for l in leads if l != {"tool": decision.tool, "args": decision.args}]
            leads.extend(l for l in new_leads if l not in leads)
            for evidence in found:
                if chain.add(evidence):
                    yield DigEvent(
                        type="evidence_found",
                        payload={"evidence": evidence.model_dump()},
                    )

        yield DigEvent(
            type="done",
            payload={
                "steps": steps,
                "evidence_count": len(chain),
                "stopped_by": stopped_by,
                "chain": chain.model_dump(),
            },
        )

    def _execute(
        self, owner: str, repo: str, decision: Decision
    ) -> tuple[list[Evidence], list[dict]]:
        """ツールを実行し、(発見した証拠, 次の掘り先候補) を返す。"""
        args = decision.args
        match decision.tool:
            case "blame_line":
                result = self._toolbox.blame_line(owner, repo, **args)
                return [result.evidence], [
                    {"tool": "get_commit", "args": {"sha": result.evidence.ref}}
                ]
            case "get_commit":
                result = self._toolbox.get_commit(owner, repo, **args)
                return [result.evidence], [
                    {"tool": "get_pr", "args": {"number": n}} for n in result.pr_numbers
                ]
            case "get_pr":
                result = self._toolbox.get_pr(owner, repo, **args)
                return [result.evidence, *result.comments], [
                    {"tool": "get_issue", "args": {"number": n}}
                    for n in result.referenced_issues
                ]
            case "get_issue":
                result = self._toolbox.get_issue(owner, repo, **args)
                return [result.evidence, *result.comments], []
            case unknown:
                raise ValueError(f"unknown tool: {unknown}")
