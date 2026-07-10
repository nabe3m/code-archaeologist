# 最終日エンハンス設計 — Oracle / evals CI / Vertex AI (2026-07-10)

締切当日(23:59)の再提出に向けた3機能。README「今後の拡張」の予告回収が主眼。
優先順: Oracle → evals CI → Vertex AI。各完了ごとにデプロイして動作確認する。

## 1. Oracle モジュール — 削除 PR への「予言」コメント

**役割**: 監査官が削除 PR を作成した直後、Oracle が「このコードが守っていた過去の障害」
を引用した警告コメントを同じ PR に投稿する。発掘→判決→PR→予言でストーリーが完結し、
「消してよい、ただし歴史を知った上で」という安全網になる。

### コンポーネント

- `models.py` — `Prophecy` モデル追加:
  - `guarded_incident: str` — このコードが守っていた過去の障害の要約。証拠番号 [n] の引用必須
  - `recurrence_symptoms: str` — 削除後にもし再発した場合に観測される兆候
  - `rollback_hint: str` — 再発時の対処(この PR を revert する等)
- `llm.py` — `prophesy(candidate: Candidate, verdict: Verdict, chain: EvidenceChain) -> Prophecy`。
  既存の `_structured()` を再利用、EXCAVATOR_MODEL(Flash)で1回だけ呼ぶ
- `github_tools.py` — `post_pr_comment(owner, repo, number, body) -> dict`。
  既存の `_post()` で `POST /repos/{owner}/{repo}/issues/{number}/comments`。戻り値に `html_url`
- `auditor.py` — コンストラクタに `prophesy` を注入(既存の judge 等と同じ関数注入パターン)。
  `pr_created` を yield した直後:
  1. 証拠チェーンが空なら **Oracle は沈黙**(コメントせず、イベントも出さない)。捏造防止の流儀を踏襲
  2. `prophesy()` → コメント本文を組み立て `post_pr_comment()` → `DigEvent(type="oracle", payload={prophecy..., comment_url})` を yield
  3. Oracle の失敗(LLM/API エラー)は `error` イベントに落として監査自体は続行(PR は既に作成済みのため)
- コメント本文フォーマット(`_oracle_body()` 静的メソッド):
  🔮 見出し + 守っていた障害(引用リンク付き) + 再発時の兆候 + 対処 + フッター
- フロントエンド — `types.ts` に `oracle` イベント型追加。`App.tsx` の監査結果カードに
  🔮 予言(guarded_incident / symptoms / コメントへのリンク)を表示

### テスト(TDD 対象はコア)

- Auditor: expired 判決時に prophesy → post_pr_comment が呼ばれ oracle イベントが出る
- Auditor: 証拠チェーンが空なら Oracle は呼ばれない(沈黙)
- Auditor: prophesy が例外を投げても監査は完走し error イベントになる
- UI・llm.py のプロンプトは動作確認ベース(プロセス圧縮の指示どおり)

### 検証

demo-repo で監査を実走 → 新しい削除 PR に予言コメントが付くのを確認 →
README・ProtoPedia 草稿のデモ PR リンクを新 PR に更新(旧 #5 はクローズせず残す)。

## 2. evals の CI 統合 — デプロイ前の品質ゲート

- `evals/run.py` に `--min-pass N` 引数を追加。exit code を `passed >= N ? 0 : 1` に
  (デフォルトは従来どおり全問)。LLM ゆらぎで 4/5 になることがあるため CI は **≥4 でゲート**
- `cloudbuild.yaml` — docker push と deploy の間にステップ追加:
  - イメージ: `ghcr.io/astral-sh/uv:python3.12-bookworm-slim`
  - `uv sync --frozen` → `uv run python evals/run.py --min-pass 4`
  - シークレット: `availableSecrets`(Secret Manager の gemini-api-key / github-token)を
    ステップの `secretEnv` で注入
  - evals は5問×多段調査で数分かかるため、ビルド全体の `timeout` を 1800s に引き上げ
- 落ちたらデプロイされない = プロンプト/モデル変更のデグレをデプロイ前に検出

## 3. Vertex AI 移行 — 鍵レス化(フォールバック付き)

- `llm.py` の `GeminiAgents.__init__`: `GOOGLE_GENAI_USE_VERTEXAI=true` なら
  `genai.Client()`(ADC + `GOOGLE_CLOUD_PROJECT` / `GOOGLE_CLOUD_LOCATION` を SDK が自動検出)、
  それ以外は従来の API キーパス
- GCP 側: `aiplatform.googleapis.com` 有効化、Cloud Run サービスアカウントに
  `roles/aiplatform.user` 付与
- デプロイ: `--set-env-vars GOOGLE_GENAI_USE_VERTEXAI=true,GOOGLE_CLOUD_PROJECT=...,GOOGLE_CLOUD_LOCATION=...`
- **API キーの secret は残す**: 締切当日のため、Vertex 側で問題が出たら env を外すだけで
  ロールバックできる状態を維持する
- 検証: ローカルで ADC + env を立てて dig 1件、デプロイ後にデモ URL で dig / audit を実走

## スコープ外

- 動画の撮り直し(予言コメントは PR スクリーンショットの差し替えで対応)
- リポジトリ全体監査 / GitHub App 化

## 仕上げ

README / ProtoPedia 草稿の「今後の拡張」から実装済み3項目を「実装した工夫」へ昇格。
最終デプロイ → デモ URL で一通り実走 → 再提出。
