# Code Archaeologist — 設計書（承認済み・圧縮版）

日付: 2026-07-05 / 締切: 2026-07-10 23:59（7/9 夜に初回提出）
イベント: DevOps × AI Agent Hackathon 2026（Findy / Google Cloud）

## 一言で

「なぜこのコードはこうなっているのか?」に、証拠付きで答えるエージェント。
git 履歴・PR 議論・Issue を自律的に遡行横断して意思決定の因果関係を再構築し、
「理由が失効したコード」には根拠付きの削除 PR を自動作成する。

## アーキテクチャ（承認済み）

```
ブラウザ ── SSE/REST ──> Cloud Run（FastAPI・単一サービス）
                          ├─ 静的配信: Web UI（Vite + React SPA）
                          ├─ 調査官 Excavator（エージェントループ）
                          ├─ 史官 Historian（回答合成）
                          └─ 監査官 Auditor（削除PR作成・Day 3）
                               │                │
                          Gemini API        GitHub API（キャッシュ層経由）
```

### 決定事項と理由

1. **単一 Cloud Run サービス**: デモ URL 1つ、デプロイ運用が半分。FastAPI が React ビルド成果物を静的配信。
2. **UI は Vite + React SPA**: 3ペイン（左コード / 右調査タイムライン / 下部回答）+ リアルタイムイベントは Streamlit では不自由。審査基準③に投資。
3. **SSE で調査過程を配信**: 単方向で十分・Cloud Run と相性良。調査官の判断を構造化イベント（`dig_decision` / `evidence_found` / `answer` 等）として発行し、UI・構造化ログ・デモ動画素材を1つの仕組みで賄う。
4. **エージェント基盤**: Day 1 冒頭に ADK スパイク（2h 上限）。詰まったら google-genai SDK + 自前ループ（function calling で GitHub ツールを自律選択）に即切替。どちらでも「次にどこを掘るか」の LLM 自律判断（審査基準①）は成立。判断理由は README に記録。
5. **Gemini**: AI Studio API キー + `google-genai` SDK。既定は Flash 系、史官の最終回答のみ上位モデル。Vertex 切替は初期化1行差 → README の拡張性節に記載。
6. **GitHub キャッシュ**: ディスク（/tmp）+ メモリ LRU。キー = API パス。デモのレート制限死を防止。demo-repo 分はウォームアップ可能。
7. **TDD 範囲はコアのみ**: 証拠チェーン構築・ツールディスパッチ・遡行ループ停止条件（LLM/GitHub はモック）。UI・ルート層は動作確認ベース。
8. **秘密情報**: ローカル .env（コミット禁止）、Cloud Run は Secret Manager。

### エージェント構成

| 役割 | 内容 | 優先度 |
|------|------|--------|
| 調査官 Excavator | 対象行 → blame → コミット → PR → 議論 → Issue を再帰遡行。各ステップの掘り先を LLM が自律判断し、構造化イベントを発行 | 最優先・TDD |
| 史官 Historian | 証拠チェーンから「いつ・誰が・なぜ・当時の制約・現在も有効か」を実 PR/Issue リンク付きで回答 | 最優先 |
| 監査官 Auditor | 理由が失効した防御的コードを検出し、発掘結果を根拠に削除 PR を自動作成 | Day 3 に間に合えば |
| 予言 Oracle | 削除 PR に過去障害 Issue を1件引用コメント（簡易版のみ） | 原則スコープ外 |

## マイルストーン

- **Day 1（7/5）**: 環境準備 → リポジトリ初期化 → ADK スパイク → 調査官+史官 CLI E2E → Cloud Run 初回デプロイ + cloudbuild.yaml
- **Day 2（7/6）**: Web UI（3ペイン・SSE タイムライン）。demo-repo 整備（「歴史のある嘘」と対応 PR/Issue を GitHub 上に実作成）
- **Day 3（7/7）**: 監査官（削除 PR 自動作成）。evals/ に考古学クイズ5問 + 確認スクリプト
- **Day 4（7/8）**: 実装凍結。動画素材収録・アーキテクチャ図（Mermaid）・README・ProtoPedia 草稿
- **Day 5（7/9）**: 夜に初回提出（再提出可）。7/10 は磨きのみ

## 完了の定義（7/9 夜）

- [ ] デプロイ URL で demo-repo への「質問 → 遡行可視化 → 出典付き回答」が安定動作
- [ ] 削除 PR が GitHub 上に実作成される（監査官が間に合った場合）
- [ ] 公開リポジトリに README・アーキテクチャ図・evals/
- [ ] 動画アップロード済み・ProtoPedia 必須項目（タグ `findy_hackathon`）完備
