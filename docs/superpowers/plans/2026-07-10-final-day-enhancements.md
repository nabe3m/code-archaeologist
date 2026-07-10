# 最終日エンハンス実装計画 — Oracle / evals CI / Vertex AI

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 削除 PR に「予言」コメントを投稿する Oracle、Cloud Build の evals 品質ゲート、Vertex AI への鍵レス移行を締切当日中にデプロイ・再提出する。

**Architecture:** Oracle は既存の関数注入パターン(Auditor に `prophesy` を注入)で追加し、GitHub コメント投稿は既存 `_post()` を再利用。evals ゲートは cloudbuild.yaml の build と deploy の間のステップ。Vertex は `GeminiAgents` の Client 初期化の env 分岐のみ(API キーはフォールバックとして残す)。

**Tech Stack:** Python 3.12 / FastAPI / google-genai SDK / React + Vite / Cloud Build / Cloud Run

## Global Constraints

- スペック: `docs/superpowers/specs/2026-07-10-final-day-enhancements-design.md`
- TDD はコアロジック(auditor / github_tools)のみ。UI・プロンプトは動作確認ベース(プロセス圧縮の指示)
- 捏造防止の流儀: 証拠チェーンが空なら Oracle は沈黙(LLM を呼ばない・コメントしない)
- GCP プロジェクト: `code-archaeologist-hackathon`、リージョン asia-northeast1、gcloud は `~/google-cloud-sdk/bin/gcloud`(個人アカウント側をアクティブに)
- このリポジトリはコミット署名無効(`commit.gpgsign false` 設定済み)。コミットメッセージ末尾に `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- デプロイ: `~/google-cloud-sdk/bin/gcloud builds submit --config cloudbuild.yaml --substitutions SHORT_SHA=$(git rev-parse --short HEAD) .`
- 本番デモ URL: https://code-archaeologist-66wzqrw33q-an.a.run.app

---

### Task 1: Prophecy モデルと Auditor への Oracle 組み込み(TDD)

**Files:**
- Modify: `src/code_archaeologist/models.py`(EventType に `oracle` 追加、`Prophecy` 追加)
- Modify: `src/code_archaeologist/auditor.py`(`prophesy` 注入、PR 作成後の Oracle 発動)
- Test: `tests/test_auditor.py`

**Interfaces:**
- Consumes: 既存の `Auditor` / `DigEvent` / `EvidenceChain`
- Produces:
  - `Prophecy(BaseModel)`: `guarded_incident: str`, `recurrence_symptoms: str`, `rollback_hint: str`
  - `Auditor.__init__(..., prophesy: Callable[[Candidate, Verdict, EvidenceChain], Prophecy] | None = None)`
  - toolbox に `post_pr_comment(owner, repo, number, body) -> dict`(`{"url": ...}`)を要求(Task 2 で実装)
  - `DigEvent(type="oracle", payload={guarded_incident, recurrence_symptoms, rollback_hint, comment_url})`

- [ ] **Step 1: 失敗するテストを書く** — `tests/test_auditor.py` に追記

`StubToolbox` にコメント投稿の記録を追加:

```python
    def post_pr_comment(self, owner, repo, number, body):
        self.calls.append(f"post_pr_comment({number})")
        self.comment_body = body
        return {"url": f"https://github.com/o/r/pull/{number}#issuecomment-1"}
```

`make_auditor` に prophesy を渡せるようにする(デフォルト None で既存テストは不変):

```python
def make_auditor(toolbox, expired=True, prophesy=None):
    ...
    auditor = Auditor(
        toolbox=toolbox,
        dig=stub_dig,
        find_candidates=find_candidates,
        forward_query=forward_query,
        judge=judge,
        prophesy=prophesy,
    )
```

新規テスト3本(ファイル末尾に追加):

```python
def stub_prophesy(candidate, chain_verdict, chain):
    from code_archaeologist.models import Prophecy

    return Prophecy(
        guarded_incident="在庫 v1 の結果整合で書き込み直後の読み取りが 404 になった [1]",
        recurrence_symptoms="注文直後の在庫参照が 404 を返す",
        rollback_hint="この PR を revert して sleep を戻す",
    )


def test_oracle_posts_prophecy_comment_after_pr_created():
    toolbox = StubToolbox()
    events = list(
        make_auditor(toolbox, prophesy=stub_prophesy).audit("o", "r", "orders/api.py")
    )
    types = [e.type for e in events]
    assert types[-2:] == ["pr_created", "oracle"]
    assert "post_pr_comment(9)" in toolbox.calls
    # コメント本文に予言の中身が入る
    assert "404" in toolbox.comment_body
    assert "revert" in toolbox.comment_body
    # UI 用イベントにコメント URL が載る
    assert events[-1].payload["comment_url"].endswith("#issuecomment-1")
    assert "404" in events[-1].payload["guarded_incident"]


def test_oracle_failure_degrades_to_error_event():
    toolbox = StubToolbox()

    def broken_prophesy(candidate, verdict, chain):
        raise RuntimeError("LLM down")

    events = list(
        make_auditor(toolbox, prophesy=broken_prophesy).audit("o", "r", "orders/api.py")
    )
    # PR は作成済みのまま、Oracle の失敗は error イベントに落ちて監査は完走する
    assert any(e.type == "pr_created" for e in events)
    assert any(e.type == "error" and "Oracle" in e.payload["message"] for e in events)
    assert all(e.type != "oracle" for e in events)


def test_oracle_stays_silent_without_evidence():
    """証拠チェーンが空なら予言しない(捏造防止)。"""
    toolbox = StubToolbox()
    toolbox.search_issues = lambda owner, repo, query: []  # 前方調査もヒットなし

    def empty_dig(owner, repo, path, line, question):
        yield DigEvent(
            type="done",
            payload={"steps": 0, "evidence_count": 0, "stopped_by": "finish",
                     "chain": EvidenceChain().model_dump()},
        )

    called = []

    def spy_prophesy(candidate, verdict, chain):
        called.append(True)
        return stub_prophesy(candidate, verdict, chain)

    auditor = make_auditor(toolbox, prophesy=spy_prophesy)
    auditor._dig = empty_dig
    events = list(auditor.audit("o", "r", "orders/api.py"))
    assert not called
    assert all(e.type != "oracle" for e in events)
```

注意: `auditor._dig = empty_dig` は実装のプライベート属性名に依存する。Step 3 の実装で属性名を `self._dig` にすること(現状どおり)。

- [ ] **Step 2: テストが失敗することを確認**

Run: `uv run pytest tests/test_auditor.py -v`
Expected: 新規3本が FAIL(`TypeError: unexpected keyword argument 'prophesy'` / `ImportError: Prophecy`)。既存3本は PASS のまま。

- [ ] **Step 3: 実装**

`src/code_archaeologist/models.py` — EventType に `oracle` を追加し、Prophecy を定義:

```python
EventType = Literal[
    "dig_started",
    "dig_decision",
    "evidence_found",
    "answer",
    "done",
    "error",
    # 監査官
    "audit_candidate",
    "verdict",
    "pr_created",
    "oracle",
]
```

ファイル末尾(DigEvent の後)に:

```python
class Prophecy(BaseModel):
    """Oracle の予言 — 削除されるコードがかつて守っていた障害の記録。

    guarded_incident の主張には証拠番号 [n] を付ける(番号は削除 PR 本文の
    「発掘された証拠」リストに対応)。
    """

    guarded_incident: str
    recurrence_symptoms: str
    rollback_hint: str
```

`src/code_archaeologist/auditor.py`:

モジュール docstring の流れに「→ 失効なら削除 PR + Oracle の予言コメント」を反映し、import を更新:

```python
from .models import DigEvent, EvidenceChain, Prophecy
```

コンストラクタに注入を追加:

```python
    def __init__(
        self,
        toolbox,
        dig: DigFn,
        find_candidates: Callable[[str, str], list[Candidate]],
        forward_query: Callable[[EvidenceChain], str],
        judge: Callable[[Candidate, EvidenceChain, str], Verdict],
        prophesy: Callable[[Candidate, Verdict, EvidenceChain], Prophecy] | None = None,
    ) -> None:
        self._toolbox = toolbox
        self._dig = dig
        self._find_candidates = find_candidates
        self._forward_query = forward_query
        self._judge = judge
        self._prophesy = prophesy
```

`audit()` の `yield DigEvent(type="pr_created", payload=pr)` の直後(同じ if ブロック内)に:

```python
                # Oracle: 削除 PR に「このコードが守っていた過去の障害」を予言コメントとして残す。
                # 証拠ゼロなら沈黙(捏造防止)。失敗しても PR は作成済みなので監査は続行。
                if self._prophesy is not None and len(chain) > 0:
                    try:
                        prophecy = self._prophesy(candidate, verdict, chain)
                        comment = self._toolbox.post_pr_comment(
                            owner, repo, pr["number"], self._oracle_body(prophecy)
                        )
                        yield DigEvent(
                            type="oracle",
                            payload={**prophecy.model_dump(), "comment_url": comment["url"]},
                        )
                    except Exception as exc:
                        yield DigEvent(
                            type="error", payload={"message": f"Oracle: {exc}"}
                        )
```

クラス末尾に静的メソッドを追加:

```python
    @staticmethod
    def _oracle_body(prophecy: Prophecy) -> str:
        return (
            "## 🔮 予言者 Oracle からの注意\n\n"
            "この削除は歴史的に正当ですが、このコードが**かつて守っていた障害**を"
            "記録しておきます。マージ後にもし同種の問題が再発したら、ここに戻ってきてください。\n\n"
            f"### 守っていた過去の障害\n\n{prophecy.guarded_incident}\n\n"
            f"### 再発した場合の兆候\n\n{prophecy.recurrence_symptoms}\n\n"
            f"### 対処\n\n{prophecy.rollback_hint}\n\n"
            "---\n*証拠番号 [n] は PR 本文の「発掘された証拠」に対応します。"
            "この注意は Code Archaeologist の Oracle モジュールが自動投稿しました。*"
        )
```

- [ ] **Step 4: テストが通ることを確認**

Run: `uv run pytest tests/test_auditor.py -v`
Expected: 6本すべて PASS

- [ ] **Step 5: 全テスト実行とコミット**

Run: `uv run pytest -q` → 全 PASS(既存 37 + 新規 3)

```bash
git add src/code_archaeologist/models.py src/code_archaeologist/auditor.py tests/test_auditor.py
git commit -m "feat: Oracle — deletion PRs get a prophecy comment citing the guarded incident

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: GitHubToolbox.post_pr_comment(TDD)

**Files:**
- Modify: `src/code_archaeologist/github_tools.py`(`create_deletion_pr` の直後にメソッド追加)
- Test: `tests/test_github_write.py`

**Interfaces:**
- Consumes: 既存の `GitHubToolbox._post()`
- Produces: `post_pr_comment(owner: str, repo: str, number: int, body: str) -> dict`(`{"url": html_url}`)

- [ ] **Step 1: 失敗するテストを書く** — `tests/test_github_write.py` の `handler` に分岐を追加し、テストを追記

`handler` の `if path == "/repos/o/r/pulls"` 分岐の前に:

```python
        if path == "/repos/o/r/issues/9/comments" and request.method == "POST":
            return httpx.Response(
                201,
                json={"html_url": "https://github.com/o/r/pull/9#issuecomment-42"},
            )
```

ファイル末尾に:

```python
def test_post_pr_comment_returns_comment_url(toolbox, write_log):
    result = toolbox.post_pr_comment("o", "r", 9, "🔮 予言")
    assert result == {"url": "https://github.com/o/r/pull/9#issuecomment-42"}
    assert ("POST", "/repos/o/r/issues/9/comments") in [(m, p) for m, p, _ in write_log]
    assert write_log[-1][2] == {"body": "🔮 予言"}
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `uv run pytest tests/test_github_write.py -v`
Expected: 新規1本が FAIL(`AttributeError: 'GitHubToolbox' object has no attribute 'post_pr_comment'`)

- [ ] **Step 3: 実装** — `github_tools.py` の `create_deletion_pr` の直後に:

```python
    def post_pr_comment(self, owner: str, repo: str, number: int, body: str) -> dict:
        """PR にコメントを投稿する(Oracle の予言の出口)。PR コメントは Issues API を使う。"""
        data = self._post(f"/repos/{owner}/{repo}/issues/{number}/comments", {"body": body})
        return {"url": data["html_url"]}
```

- [ ] **Step 4: テストが通ることを確認**

Run: `uv run pytest tests/test_github_write.py -v` → 全 PASS

- [ ] **Step 5: コミット**

```bash
git add src/code_archaeologist/github_tools.py tests/test_github_write.py
git commit -m "feat: post_pr_comment — Oracle's exit to GitHub

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: llm.prophesy と web/cli への配線

**Files:**
- Modify: `src/code_archaeologist/llm.py`(prophesy 追加)
- Modify: `src/code_archaeologist/web.py:114-120`(Auditor 構築に prophesy 追加)
- Modify: `src/code_archaeologist/cli.py`(同上 + oracle イベント表示)

**Interfaces:**
- Consumes: Task 1 の `Prophecy`、`GeminiAgents._structured()`
- Produces: `GeminiAgents.prophesy(candidate: Candidate, verdict: Verdict, chain: EvidenceChain) -> Prophecy`

- [ ] **Step 1: llm.py に prophesy を実装**

import に Prophecy を追加:

```python
from .models import EvidenceChain, Prophecy
```

`judge()` の直後(`# ---- 監査官用 ----` セクション内)に:

```python
    def prophesy(
        self, candidate: Candidate, verdict: Verdict, chain: EvidenceChain
    ) -> Prophecy:
        return self._structured(
            "あなたは削除 PR に警告を残す「予言者 Oracle」です。削除されるコードが"
            "かつて守っていた障害を証拠チェーンから特定し、削除後にもし問題が再発した"
            "場合に備えた注意書きを作ってください。\n"
            "- guarded_incident: このコードが守っていた過去の障害の要約(2〜3文)。"
            "主張には必ず証拠番号 [n] を付ける\n"
            "- recurrence_symptoms: 再発した場合に観測されるであろう具体的な兆候"
            "(エラー・症状。1〜2文)\n"
            "- rollback_hint: 再発時の対処。この PR の revert を第一手として含める(1〜2文)\n\n"
            f"## 削除されるコード: {candidate.line} 行目の `{candidate.snippet}`\n\n"
            f"## 削除の判定理由(失効の根拠)\n{verdict.justification}\n\n"
            f"## 証拠チェーン(番号は引用用)\n{chain.as_context()}",
            Prophecy,
        )
```

- [ ] **Step 2: web.py の Auditor 構築に配線** — `/api/audit` 内:

```python
    auditor = Auditor(
        toolbox=toolbox,
        dig=excavator.dig,
        find_candidates=agents.find_candidates,
        forward_query=agents.forward_query,
        judge=agents.judge,
        prophesy=agents.prophesy,
    )
```

- [ ] **Step 3: cli.py に配線と表示を追加**

`main_audit()` の Auditor 構築に同じく `prophesy=agents.prophesy,` を追加。
`ICONS` に `"oracle": "🔮",` を追加。`main_audit()` の match に case を追加(`pr_created` の後):

```python
            case "oracle":
                print(f"{icon} 予言を PR にコメントしました: {p['comment_url']}")
                print(f"   守っていた障害: {p['guarded_incident']}")
```

- [ ] **Step 4: 動作確認(インポートとテスト)**

Run: `uv run pytest -q && uv run python -c "from code_archaeologist.web import app; print('ok')"`
Expected: 全 PASS + `ok`

- [ ] **Step 5: コミット**

```bash
git add src/code_archaeologist/llm.py src/code_archaeologist/web.py src/code_archaeologist/cli.py
git commit -m "feat: wire Oracle prophesy into web and CLI auditors

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: フロントエンドに 🔮 予言を表示

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/App.tsx`(AuditResult 拡張 + oracle イベント処理)
- Modify: `frontend/src/components/AnswerPane.tsx`(VerdictCard に予言表示)
- Modify: `frontend/src/components/Timeline.tsx`(タイムラインに oracle エントリ)
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Consumes: SSE の `oracle` イベント(payload: guarded_incident / recurrence_symptoms / rollback_hint / comment_url)
- Produces: `Prophecy` interface、`AuditResult.oracle: Prophecy | null`

- [ ] **Step 1: types.ts** — DigEvent union に追加(`pr_created` の行の後):

```ts
  | { type: "oracle"; payload: Prophecy };
```

(`pr_created` 行末の `;` を `|` 連結に変更することに注意)

interface を追加:

```ts
export interface Prophecy {
  guarded_incident: string;
  recurrence_symptoms: string;
  rollback_hint: string;
  comment_url: string;
}
```

- [ ] **Step 2: App.tsx** — import に `Prophecy` を追加し、`AuditResult` を拡張:

```ts
export interface AuditResult {
  verdict: Verdict;
  prUrl: string | null;
  oracle: Prophecy | null;
}
```

`case "verdict":` の setAuditResults を `{ verdict: event.payload, prUrl: null, oracle: null }` に変更。
`case "pr_created":` の後に:

```ts
          case "oracle":
            setAuditResults((prev) =>
              prev.map((r, i) =>
                i === prev.length - 1 ? { ...r, oracle: event.payload } : r,
              ),
            );
            break;
```

- [ ] **Step 3: AnswerPane.tsx** — import に `Prophecy` を追加。`VerdictCard` を oracle 対応に:

```tsx
function OracleNote({ oracle }: { oracle: Prophecy }) {
  return (
    <div className="oracle-note">
      <p className="oracle-title">🔮 Oracle の予言 — このコードが守っていた障害</p>
      <p>{oracle.guarded_incident}</p>
      <p>
        <strong>再発の兆候:</strong> {oracle.recurrence_symptoms}
      </p>
      <p>
        <strong>対処:</strong> {oracle.rollback_hint}
      </p>
      <a href={oracle.comment_url} target="_blank" rel="noreferrer">
        PR に投稿された予言コメントを見る →
      </a>
    </div>
  );
}
```

`VerdictCard` のシグネチャを `{ verdict, prUrl, oracle }: { verdict: Verdict; prUrl: string | null; oracle: Prophecy | null }` に変更し、`pr-link` 表示の直後(三項演算子の外、`keep-note` の分岐の後)に `{oracle ? <OracleNote oracle={oracle} /> : null}` を追加。
`AuditResults` の呼び出しを `<VerdictCard key={i} verdict={r.verdict} prUrl={r.prUrl} oracle={r.oracle} />` に変更。

- [ ] **Step 4: Timeline.tsx** — `case "pr_created":` の後に:

```tsx
    case "oracle":
      return (
        <li className="entry evidence">
          <span className="entry-icon">🔮</span>
          <div>
            <div className="entry-title">Oracle の予言を PR にコメント</div>
            <div className="entry-body">
              <a href={event.payload.comment_url} target="_blank" rel="noreferrer">
                守っていた障害と再発時の対処を記録しました
              </a>
            </div>
          </div>
        </li>
      );
```

- [ ] **Step 5: styles.css** — `.keep-note` ブロックの後に追加(既存の verdict-card 系のトーンに合わせる):

```css
.oracle-note {
  margin-top: 0.75rem;
  padding: 0.75rem 1rem;
  border-left: 3px solid #a855f7;
  background: rgba(168, 85, 247, 0.08);
  border-radius: 6px;
  font-size: 0.92em;
}

.oracle-note .oracle-title {
  font-weight: 600;
  margin-bottom: 0.4rem;
}
```

- [ ] **Step 6: ビルド確認**

Run: `cd frontend && npm run build && cd ..`
Expected: tsc + vite build 成功

- [ ] **Step 7: コミット**

```bash
git add frontend/src
git commit -m "feat: show Oracle prophecy in audit results and timeline

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Oracle の実機 E2E — demo-repo で監査を実走

**Files:**
- Modify: `README.md`(デモ PR リンクを新 PR に更新)
- Modify: `docs/protopedia-draft.md`(同上)

**Interfaces:**
- Consumes: Task 1〜4 の全成果。`.env` の GEMINI_API_KEY / GITHUB_TOKEN

- [ ] **Step 1: ローカルサーバを最新コードで再起動**

```bash
kill $(lsof -ti :8080) 2>/dev/null; sleep 1
(uv run uvicorn code_archaeologist.web:app --port 8080 >/tmp/ca-uvicorn.log 2>&1 &)
sleep 3 && curl -s http://localhost:8080/api/health
```

Expected: `{"ok":true}`

- [ ] **Step 2: 実監査を実行(GitHub 上に実 PR + 実コメントが作られる)**

```bash
curl -sN "http://localhost:8080/api/audit?repo=nabe3m/demo-repo&path=orders/api.py" | tee /tmp/audit-run.log
```

Expected: SSE ストリームに `verdict`(sleep 側は expired=true / 決済リトライ側は expired=false)→ `pr_created` → `oracle` イベント。`oracle` の payload に `comment_url` があること。

- [ ] **Step 3: GitHub 上で目視確認**

```bash
grep -o '"comment_url": "[^"]*"' /tmp/audit-run.log
gh pr view <新PR番号> --repo nabe3m/demo-repo --comments | head -60
```

Expected: 新しい削除 PR に「🔮 予言者 Oracle からの注意」コメントが付き、守っていた障害(Issue #1 の 404)への引用がある。

- [ ] **Step 4: ブラウザで UI 確認** — http://localhost:8080 を開いて監査を1回流し、判決カードに 🔮 予言と PR コメントへのリンクが表示されることを確認(スクリーンショットは ProtoPedia 差し替え用に保存)。UI 実走は Step 2 と別 PR がもう1本できるが、demo-repo はデモ用なので許容(不要なら古い方をクローズ)。

- [ ] **Step 5: README とProtoPedia 草稿のデモ PR リンクを更新**

- `README.md` の「エージェントが実際に作成した削除 PR」リンクと本文中の `pull/5` 参照を、Oracle コメント付きの新 PR の URL に更新(旧 #5 はクローズしない)
- `README.md` の「今後の拡張」から Oracle の行を削除し、「3人のエージェント」表に予言者の行を追加、または監査官の説明に「削除 PR には Oracle が『守っていた障害』を予言コメントとして残す」を追記
- `docs/protopedia-draft.md` の実例 URL も同じ新 PR に更新

- [ ] **Step 6: コミット**

```bash
git add README.md docs/protopedia-draft.md
git commit -m "docs: point demo PR links at the Oracle-annotated deletion PR

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: evals に --min-pass を追加

**Files:**
- Modify: `evals/run.py`

**Interfaces:**
- Produces: `python evals/run.py --min-pass N` — exit 0 は `passed >= N`(未指定なら従来どおり全問合格が条件)

- [ ] **Step 1: 実装** — `main()` の argparse に追加:

```python
    parser.add_argument(
        "--min-pass", type=int, default=None,
        help="合格ライン(この数以上 pass で exit 0)。未指定なら全問合格が条件",
    )
```

末尾の exit 判定を差し替え:

```python
    required = args.min_pass if args.min_pass is not None else len(results)
    sys.exit(0 if passed >= required else 1)
```

- [ ] **Step 2: 動作確認(LLM を呼ばずに引数だけ)**

Run: `uv run python evals/run.py --help`
Expected: `--min-pass` がヘルプに出る

Run: `uv run python evals/run.py --id no-such-id --min-pass 0; echo "exit=$?"`
Expected: 質問 0 件で `== 0/0 passed ==`、`exit=0`(min-pass 0 なので成功)

- [ ] **Step 3: コミット**

```bash
git add evals/run.py
git commit -m "feat: evals --min-pass threshold for CI gating

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: Cloud Build に evals 品質ゲートを追加してデプロイ

**Files:**
- Modify: `cloudbuild.yaml`

**Interfaces:**
- Consumes: Task 6 の `--min-pass`、Secret Manager の `gemini-api-key` / `github-token`

- [ ] **Step 1: Cloud Build 実行 SA に Secret アクセスを付与**

```bash
GCLOUD=~/google-cloud-sdk/bin/gcloud
PROJECT=code-archaeologist-hackathon
PN=$($GCLOUD projects describe $PROJECT --format='value(projectNumber)')
for s in gemini-api-key github-token; do
  $GCLOUD secrets add-iam-policy-binding $s --project=$PROJECT \
    --member="serviceAccount:${PN}-compute@developer.gserviceaccount.com" \
    --role=roles/secretmanager.secretAccessor
done
```

(新しめのプロジェクトの Cloud Build デフォルト SA は compute SA。もし Step 3 のビルドで
`PERMISSION_DENIED` が出たら legacy SA `${PN}@cloudbuild.gserviceaccount.com` にも同じ binding を付与)

- [ ] **Step 2: cloudbuild.yaml に evals ゲートを追加**

docker push ステップと deploy ステップの間に:

```yaml
  # 品質ゲート: プロンプト/モデル変更のデグレをデプロイ前に検出する。
  # LLM のゆらぎで 5/5 が 4/5 になることがあるため合格ラインは 4。
  - name: ghcr.io/astral-sh/uv:python3.12-bookworm-slim
    id: evals-gate
    entrypoint: sh
    args:
      - -c
      - uv sync --frozen --no-dev && uv run --no-sync python evals/run.py --min-pass 4
    secretEnv: ["GEMINI_API_KEY", "GITHUB_TOKEN"]
```

ファイル末尾(images: の後)に:

```yaml
availableSecrets:
  secretManager:
    - versionName: projects/$PROJECT_ID/secrets/gemini-api-key/versions/latest
      env: GEMINI_API_KEY
    - versionName: projects/$PROJECT_ID/secrets/github-token/versions/latest
      env: GITHUB_TOKEN

# evals は 5 問 × 多段 LLM 調査で数分かかる
timeout: 1800s
```

- [ ] **Step 3: コミットしてビルド実行(Oracle も本番に載る)**

```bash
git add cloudbuild.yaml
git commit -m "feat: evals quality gate in Cloud Build — no deploy below 4/5

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
~/google-cloud-sdk/bin/gcloud builds submit --config cloudbuild.yaml \
  --substitutions SHORT_SHA=$(git rev-parse --short HEAD) . --project=code-archaeologist-hackathon
```

Expected: ビルドログに evals の `== N/5 passed ==`(N≥4)が出てから deploy が走り、SUCCESS。

注意: このビルドで作られる実 PR はない(evals は読み取り調査のみ)。

- [ ] **Step 4: 本番確認**

```bash
curl -s https://code-archaeologist-66wzqrw33q-an.a.run.app/api/health
```

Expected: `{"ok":true}`。ブラウザでデモ URL を開き、監査を1回流して 🔮 が出ることを確認。

---

### Task 8: Vertex AI 移行(鍵レス化・フォールバック付き)

**Files:**
- Modify: `src/code_archaeologist/llm.py:107-109`(Client 初期化の分岐)
- Modify: `cloudbuild.yaml`(deploy ステップに env 追加)
- Modify: `README.md`(今後の拡張 → 実装済みへ)

**Interfaces:**
- Produces: env `GOOGLE_GENAI_USE_VERTEXAI=true` + `GOOGLE_CLOUD_PROJECT` + `GOOGLE_CLOUD_LOCATION` で Vertex AI 経由になる `GeminiAgents`

- [ ] **Step 1: llm.py の Client 初期化を分岐**

```python
class GeminiAgents:
    def __init__(self, api_key: str | None = None) -> None:
        if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() == "true":
            # Vertex AI: ADC + GOOGLE_CLOUD_PROJECT / GOOGLE_CLOUD_LOCATION を SDK が読む。
            # Cloud Run では Workload Identity により鍵レス
            self._client = genai.Client()
        else:
            self._client = genai.Client(api_key=api_key or os.environ["GEMINI_API_KEY"])
```

モジュール docstring の「Vertex AI へは Client 初期化の切替のみで移行できる」を「`GOOGLE_GENAI_USE_VERTEXAI=true` で Vertex AI 経由(鍵レス)」に更新。

Run: `uv run pytest -q` → 全 PASS

- [ ] **Step 2: GCP 側の準備**

```bash
GCLOUD=~/google-cloud-sdk/bin/gcloud
PROJECT=code-archaeologist-hackathon
PN=$($GCLOUD projects describe $PROJECT --format='value(projectNumber)')
$GCLOUD services enable aiplatform.googleapis.com --project=$PROJECT
# Cloud Run のランタイム SA(デフォルト compute SA)に Vertex 利用権限
$GCLOUD projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:${PN}-compute@developer.gserviceaccount.com" \
  --role=roles/aiplatform.user
```

- [ ] **Step 3: cloudbuild.yaml の deploy ステップに env を追加**

deploy ステップの args に1行追加(`--set-secrets` の行の後。secrets は**フォールバックとして残す**):

```yaml
      - --set-env-vars=GOOGLE_GENAI_USE_VERTEXAI=true,GOOGLE_CLOUD_PROJECT=code-archaeologist-hackathon,GOOGLE_CLOUD_LOCATION=global
```

(モデル gemini-2.5-flash / 2.5-pro は global エンドポイントで利用可能。ロールバックは
`gcloud run services update code-archaeologist --region=asia-northeast1 --update-env-vars=GOOGLE_GENAI_USE_VERTEXAI=false`
の1コマンド)

- [ ] **Step 4: README 更新** — 「今後の拡張」から Vertex AI 移行と evals CI 統合の行を削除し、
「技術選定の理由」または「アーキテクチャ」節に以下を反映:

- 「LLM は Vertex AI 経由(Workload Identity で鍵レス)。`GOOGLE_GENAI_USE_VERTEXAI` で Developer API にも切替可能」
- 「evals は Cloud Build の品質ゲートとしてデプロイ前に実行(4/5 未満はデプロイ中止)」
- 「監査」節: Oracle の予言コメントについて1行

- [ ] **Step 5: コミット・デプロイ・本番実走**

```bash
git add src/code_archaeologist/llm.py cloudbuild.yaml README.md
git commit -m "feat: Vertex AI via env switch — keyless on Cloud Run, API-key fallback kept

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
~/google-cloud-sdk/bin/gcloud builds submit --config cloudbuild.yaml \
  --substitutions SHORT_SHA=$(git rev-parse --short HEAD) . --project=code-archaeologist-hackathon
```

Expected: evals ゲート通過(このビルドの evals は Developer API キーで走る。本番ランタイムのみ Vertex)→ deploy SUCCESS。

デプロイ後、デモ URL で dig を1回・監査を1回実走して回答・判決・🔮 が出ることを確認。
問題があれば Step 3 記載のロールバックコマンドで即 Developer API に戻す。

- [ ] **Step 6: 仕上げの確認と再提出**

- `git status` がクリーン、`git push` 済みであること
- ProtoPedia の掲載内容(スクリーンショット・PR リンク・特徴の記述)を最新化して再提出
- デモ URL・デモ PR・リポジトリの3リンクを最終クリック確認

---

## Self-Review 済み

- スペック3機能すべてにタスクあり(Oracle: 1-5 / evals CI: 6-7 / Vertex: 8)
- 型整合: `Prophecy` のフィールド名は models.py / llm.py / types.ts / AnswerPane で一致。`post_pr_comment` の戻り値 `{"url"}` は auditor の `comment["url"]` と一致
- 実 PR を作る操作は Task 5 Step 2/4 と明記(demo-repo はデモ専用リポジトリ)
