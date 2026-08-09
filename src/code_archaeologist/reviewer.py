"""レビュー officer — PR で消されようとしている防御的コードを、消される前に止める。

監査官（Auditor）が「失効したコードを消す」出口なのに対し、こちらは
「**まだ生きている**コードが消されるのを止める」入口。

設計上の要点は発火の向き。発掘 UI は「人が質問する」pull 型で、質問できる人は
すでにその行を怪しんでいる＝一番助けを必要としていない人だった。事故を起こすのは
歴史を知らずに何気なく消す人で、その人は質問しない。だからこのモジュールは
pull_request をトリガに、人が何もしていないところへ割り込む。

判定経路は Auditor.investigate をそのまま共有する（発掘 → 失効確認の強制実行 →
判決）。判定基準がレビューと監査で食い違わないようにするため。
"""

import re
from collections.abc import Callable, Iterator

from pydantic import BaseModel

from .auditor import Candidate, Verdict
from .models import REVIEW_COMMENT_MARKER, DigEvent, EvidenceChain, Prophecy

_HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+")


def removed_lines(patch: str) -> set[int]:
    """unified diff から「base 側で削除された行番号」を取り出す。

    候補検出は base 側のファイル本文に対して行うので、行番号も base 側で揃える。
    """
    removed: set[int] = set()
    line_no = 0
    for raw in patch.splitlines():
        hunk = _HUNK.match(raw)
        if hunk:
            line_no = int(hunk.group(1))
        elif raw.startswith("-"):
            removed.add(line_no)
            line_no += 1
        elif raw.startswith("+") or raw.startswith("\\"):
            continue  # 追加行は base 側の行番号を進めない / "\ No newline" は無視
        else:
            line_no += 1  # 文脈行（先頭スペース、または空行）
    return removed


class ReviewFinding(BaseModel):
    path: str
    candidate: Candidate
    verdict: Verdict
    prophecy: Prophecy | None = None
    comment_url: str | None = None


InvestigateFn = Callable[..., Iterator[DigEvent]]


class PrReviewer:
    def __init__(
        self,
        toolbox,
        investigate: InvestigateFn,
        find_candidates: Callable[[str, str], list[Candidate]],
        prophesy: Callable[[Candidate, Verdict, EvidenceChain], Prophecy] | None = None,
        post: bool = True,
    ) -> None:
        self._toolbox = toolbox
        self._investigate = investigate
        self._find_candidates = find_candidates
        self._prophesy = prophesy
        self._post = post

    def review(self, owner: str, repo: str, number: int) -> Iterator[DigEvent]:
        # 審査中の PR を前方検索から締め出す。これが無いと、前方検索が自分の
        # 立てた PR を掘り当て、自分が投稿した警告コメントを「一次資料」として
        # 引用しはじめる（実測済み: demo-repo #17 で判定理由に自分の警告が
        # 証拠 [7] として混入した）。
        exclude = getattr(self._toolbox, "exclude_numbers", None)
        if exclude is not None:
            exclude.add(number)

        diff = self._toolbox.get_pr_diff(owner, repo, number)

        for pr_file in diff.files:
            removed = removed_lines(pr_file.patch)
            if not removed:
                continue

            # 候補検出も発掘も base 側で行う。PR ブランチには既にその行が無い。
            base_code = self._toolbox.get_file(
                owner, repo, pr_file.path, ref=diff.base_sha
            )
            targets = [
                c
                for c in self._find_candidates(pr_file.path, base_code)
                if c.line in removed
            ]
            for candidate in targets:
                yield DigEvent(
                    type="review_target",
                    payload={"path": pr_file.path, **candidate.model_dump()},
                )
                yield from self._review_candidate(
                    owner, repo, number, pr_file.path, candidate, base_code
                )

    def _review_candidate(
        self,
        owner: str,
        repo: str,
        number: int,
        path: str,
        candidate: Candidate,
        base_code: str,
    ) -> Iterator[DigEvent]:
        chain, verdict = yield from self._investigate(
            owner, repo, path, candidate, base_code
        )

        # 「この行が何を守っているか」は、消してよい場合も消してはいけない場合も
        # レビュアーが等しく知りたい情報なので、どちらの判定でも Oracle を呼ぶ。
        # 証拠ゼロなら沈黙（捏造防止）。
        prophecy = None
        if self._prophesy is not None and len(chain) > 0:
            try:
                prophecy = self._prophesy(candidate, verdict, chain)
            except Exception as exc:
                yield DigEvent(type="error", payload={"message": f"Oracle: {exc}"})

        finding = ReviewFinding(
            path=path, candidate=candidate, verdict=verdict, prophecy=prophecy
        )
        if self._post:
            try:
                comment = self._toolbox.post_pr_comment(
                    owner, repo, number, self._body(finding, self._sources(chain))
                )
                finding.comment_url = comment["url"]
            except Exception as exc:
                yield DigEvent(
                    type="error", payload={"message": f"review comment: {exc}"}
                )

        yield DigEvent(
            type="review_finding",
            payload={
                **finding.model_dump(),
                "evidence_count": len(chain),
                "sources": self._sources(chain),
            },
        )

    @staticmethod
    def _sources(chain: EvidenceChain) -> str:
        return "\n".join(
            f"{i}. [{e.label()} — {e.title}]({e.url})"
            for i, e in enumerate(chain.items, start=1)
        )

    def _body(self, finding: ReviewFinding, sources: str) -> str:
        loc = f"`{finding.path}:{finding.candidate.line}`"
        snippet = f"`{finding.candidate.snippet}`"
        prophecy = finding.prophecy

        if not finding.verdict.expired:
            body = (
                f"{REVIEW_COMMENT_MARKER}\n"
                "## 🚨 Code Archaeologist — この削除は危険です\n\n"
                f"{loc} の {snippet} は、**理由となった制約がまだ有効な**"
                "防御的コードです。この PR はそれを削除しています。\n\n"
                f"### 判定理由\n\n{finding.verdict.justification}\n"
            )
            if prophecy is not None:
                body += (
                    f"\n### この行が守っているもの\n\n{prophecy.guarded_incident}\n\n"
                    f"### 消した場合に現れる兆候\n\n{prophecy.recurrence_symptoms}\n\n"
                    f"### どうしても消すなら\n\n{prophecy.rollback_hint}\n"
                )
        else:
            body = (
                f"{REVIEW_COMMENT_MARKER}\n"
                "## ✅ Code Archaeologist — この削除は歴史的に妥当です\n\n"
                f"{loc} の {snippet} は、**理由がすでに失効した**防御的コードでした。"
                "削除して問題ありません。\n\n"
                f"### 判定理由\n\n{finding.verdict.justification}\n"
            )
            if prophecy is not None:
                body += (
                    f"\n### 念のため: この行が守っていた障害\n\n"
                    f"{prophecy.guarded_incident}\n\n"
                    f"### 再発した場合の兆候\n\n{prophecy.recurrence_symptoms}\n"
                )

        if sources:
            body += (
                f"\n### 発掘された証拠（番号は判定理由の [n] に対応）\n\n{sources}\n"
            )
        body += (
            "\n---\n*このコメントは Code Archaeologist が PR の削除行を検出し、"
            "git 履歴・PR 議論・Issue を自律的に遡行して自動投稿しました。*"
        )
        return body
