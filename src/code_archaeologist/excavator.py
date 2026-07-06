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


# decide(question, chain, leads, target, executed) — target は owner/repo/path/line、
# executed は実行済み呼び出しのリスト。LLM がパスを幻覚したり同じ手を
# 繰り返したりしないよう、正確な文脈を毎回渡す。
DecideFn = Callable[[str, EvidenceChain, list[dict], dict, list[dict]], Decision]


class Excavator:
    def __init__(self, toolbox, decide: DecideFn, max_steps: int = 12) -> None:
        self._toolbox = toolbox
        self._decide = decide
        self._max_steps = max_steps

    def dig(
        self,
        owner: str,
        repo: str,
        path: str,
        line: int,
        question: str,
        line_end: int | None = None,
    ) -> Iterator[DigEvent]:
        chain = EvidenceChain()
        if line_end and line_end > line:
            first_lead = {"tool": "blame_range", "args": {"path": path, "start": line, "end": line_end}}
        else:
            first_lead = {"tool": "blame_line", "args": {"path": path, "line": line}}
        leads: list[dict] = [first_lead]
        target = {"owner": owner, "repo": repo, "path": path, "line": line, "line_end": line_end}
        executed: list[dict] = []
        finish_rejected = False
        stopped_by = "finish"

        yield DigEvent(
            type="dig_started",
            payload={"question": question, "target": target},
        )

        steps = 0
        while True:
            if steps >= self._max_steps:
                stopped_by = "max_steps"
                break
            decision = self._decide(question, chain, leads, target, executed)
            steps += 1
            if decision.tool == "finish":
                # 自己点検: 未消化のリードや search_issues 未実行のまま早期終了する
                # 傾向（LLM の満足化バイアス）を一度だけ差し戻して再考させる
                searched = any(
                    e["tool"] == "search_issues" and e["outcome"] == "ok" for e in executed
                )
                if not finish_rejected and (leads or not searched):
                    finish_rejected = True
                    reasons = []
                    if leads:
                        reasons.append("未消化の掘り先候補が残っています")
                    if not searched:
                        reasons.append(
                            "search_issues 未実行です（当時の制約がその後解消されていないか確認）"
                        )
                    note = "。".join(reasons) + "。質問の全部分に証拠付きで答えられるか再確認してください"
                    executed.append({"tool": "finish", "args": {}, "outcome": f"rejected: {note}"})
                    yield DigEvent(
                        type="error",
                        payload={"tool": "finish", "message": f"自己点検で差し戻し: {note}"},
                    )
                    continue
                yield DigEvent(
                    type="dig_decision",
                    payload={"tool": "finish", "args": {}, "reason": decision.reason},
                )
                break
            yield DigEvent(
                type="dig_decision",
                payload={"tool": decision.tool, "args": decision.args, "reason": decision.reason},
            )

            call = {"tool": decision.tool, "args": decision.args}
            if any(e["tool"] == call["tool"] and e["args"] == call["args"] for e in executed):
                yield DigEvent(
                    type="error",
                    payload={"tool": decision.tool, "message": "実行済みの呼び出しです（スキップ）"},
                )
                continue

            try:
                found, new_leads = self._execute(owner, repo, decision)
            except Exception as exc:  # 幻覚ツール名や API エラーでもループは止めない
                # 結果を履歴に残す: LLM が次の判断でエラーから学べるようにする
                executed.append({**call, "outcome": f"error: {exc}"})
                yield DigEvent(
                    type="error",
                    payload={"tool": decision.tool, "message": str(exc)},
                )
                continue

            executed.append({**call, "outcome": "ok"})
            leads = [lead for lead in leads if lead != call]
            leads.extend(
                lead
                for lead in new_leads
                if lead not in leads
                and not any(
                    e["tool"] == lead["tool"] and e["args"] == lead["args"] for e in executed
                )
            )
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
            case "blame_range":
                evidences = self._toolbox.blame_range(owner, repo, **args)
                return list(evidences), [
                    {"tool": "get_commit", "args": {"sha": e.ref}} for e in evidences
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
            case "search_issues":
                hits = self._toolbox.search_issues(owner, repo, **args)
                return [], [
                    {
                        "tool": "get_pr" if hit["is_pr"] else "get_issue",
                        "args": {"number": hit["number"]},
                    }
                    for hit in hits
                ]
            case unknown:
                raise ValueError(f"unknown tool: {unknown}")
