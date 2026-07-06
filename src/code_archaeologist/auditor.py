"""監査官（Auditor）— 理由が失効した防御的コードを検出し、証拠付き削除 PR を作る。

流れ: 候補検出（LLM）→ 発掘（調査官を再利用）→ 失効確認（search_issues を
決め打ちで実行し、ヒットした Issue/PR も読む）→ 判決（LLM・引用必須）→
失効なら GitHub 上に削除 PR を実作成。

search_issues を LLM の裁量に任せず監査官自身が実行するのは、
「制約のその後」の確認が監査の定義そのものだから。
"""

import re
import time
from collections.abc import Callable, Iterator

from pydantic import BaseModel

from .models import DigEvent, EvidenceChain


class Candidate(BaseModel):
    line: int
    snippet: str
    reason: str


class Verdict(BaseModel):
    expired: bool
    justification: str  # [n] 形式で証拠を引用
    lines_to_remove: list[int]


DigFn = Callable[..., Iterator[DigEvent]]

_MAX_FORWARD_HITS = 4


class Auditor:
    def __init__(
        self,
        toolbox,
        dig: DigFn,
        find_candidates: Callable[[str, str], list[Candidate]],
        forward_query: Callable[[EvidenceChain], str],
        judge: Callable[[Candidate, EvidenceChain, str], Verdict],
    ) -> None:
        self._toolbox = toolbox
        self._dig = dig
        self._find_candidates = find_candidates
        self._forward_query = forward_query
        self._judge = judge

    def audit(self, owner: str, repo: str, path: str) -> Iterator[DigEvent]:
        code = self._toolbox.get_file(owner, repo, path)
        candidates = self._find_candidates(path, code)
        for candidate in candidates:
            yield DigEvent(type="audit_candidate", payload=candidate.model_dump())

        for candidate in candidates:
            chain = EvidenceChain()
            question = (
                f"{path}:{candidate.line} の `{candidate.snippet}` はなぜ存在する? "
                "その理由となった制約は現在も有効か?"
            )
            for event in self._dig(owner, repo, path, candidate.line, question):
                if event.type == "done":
                    chain = EvidenceChain.model_validate(event.payload["chain"])
                yield event

            # 失効確認（強制実行）: 当時の制約がその後解消されていないかを前方調査する
            query = self._forward_query(chain)
            hits = self._toolbox.search_issues(owner, repo, query)
            for hit in hits[:_MAX_FORWARD_HITS]:
                try:
                    if hit["is_pr"]:
                        result = self._toolbox.get_pr(owner, repo, hit["number"])
                        found = [result.evidence, *result.comments]
                    else:
                        result = self._toolbox.get_issue(owner, repo, hit["number"])
                        found = [result.evidence, *result.comments]
                except Exception as exc:
                    yield DigEvent(type="error", payload={"message": str(exc)})
                    continue
                for evidence in found:
                    if chain.add(evidence):
                        yield DigEvent(
                            type="evidence_found",
                            payload={"evidence": evidence.model_dump()},
                        )

            verdict = self._judge(candidate, chain, code)
            yield DigEvent(
                type="verdict",
                payload={**verdict.model_dump(), "candidate": candidate.model_dump()},
            )

            if verdict.expired and verdict.lines_to_remove:
                slug = re.sub(r"[^a-z0-9]+", "-", candidate.snippet.lower()).strip("-")[:40]
                slug = f"{slug}-{int(time.time()) % 100000}"  # 再監査時のブランチ名衝突を回避
                pr = self._toolbox.create_deletion_pr(
                    owner,
                    repo,
                    path=path,
                    lines=verdict.lines_to_remove,
                    branch=f"code-archaeologist/remove-{slug}-L{candidate.line}",
                    title=f"chore: 理由が失効した防御的コードを削除 ({path}:{candidate.line})",
                    body=self._pr_body(candidate, verdict, chain, path),
                    commit_message=(
                        f"chore: remove expired workaround at {path}:{candidate.line}\n\n"
                        "Detected and excavated by Code Archaeologist."
                    ),
                )
                yield DigEvent(type="pr_created", payload=pr)

    @staticmethod
    def _pr_body(
        candidate: Candidate, verdict: Verdict, chain: EvidenceChain, path: str
    ) -> str:
        sources = "\n".join(
            f"{i}. [{e.label()} — {e.title}]({e.url})"
            for i, e in enumerate(chain.items, start=1)
        )
        return (
            f"## 🏺 Code Archaeologist による監査結果\n\n"
            f"`{path}:{candidate.line}` の `{candidate.snippet}` は"
            f"**理由が失効した防御的コード**と判定しました。\n\n"
            f"### 判定理由\n\n{verdict.justification}\n\n"
            f"### 発掘された証拠（番号は判定理由の [n] に対応）\n\n{sources}\n\n"
            f"---\n*この PR は Code Archaeologist が git 履歴・PR 議論・Issue を"
            f"自律的に遡行して自動作成しました。*"
        )
