# Code Archaeologist

**「なぜこのコードはこうなっているのか?」に、証拠付きで答える AI エージェント。**

git 履歴・PR 議論・Issue を自律的に遡行横断し、コードの意思決定の因果関係を再構築します。さらに「理由が失効したコード」を検出し、発掘した証拠を根拠に添えた削除 PR を自動作成します。

> DevOps × AI Agent Hackathon 2026（Findy 主催 / Google Cloud 協賛）提出作品

## エージェント構成

| 役割 | 何をするか |
|------|-----------|
| 🔍 調査官 Excavator | 対象コード行から git blame → コミット → PR → 議論 → Issue を再帰的に遡行。**各ステップで「次にどこを掘るか」を LLM が自律判断** |
| 📜 史官 Historian | 証拠チェーンから「いつ・誰が・なぜ・当時の制約・その制約は現在も有効か」を、実在の PR/Issue へのリンク付きで回答 |
| ⚖️ 監査官 Auditor | 理由が失効した防御的コードを検出し、発掘結果を根拠に削除 PR を自動作成 |

## アーキテクチャ

（Day 4 に Mermaid 図を掲載）

- 実行環境: **Google Cloud Run**（単一サービス: FastAPI + React SPA + SSE）
- AI: **Gemini API**（google-genai SDK）
- GitHub 連携: REST/GraphQL + ローカルキャッシュ

### 技術選定の理由

**エージェント基盤: google-genai SDK 直利用 + 自前遡行ループ**（ADK は Day 1 スパイクの結果、不採用）

Day 1 に ADK（Agent Development Kit）のスパイクを実施（`spikes/adk_spike.py`）。ADK でも blame → コミット → PR → Issue の自律遡行ループ自体は動作したが、以下の理由で自前ループを採用した:

1. **判断の構造化**: 本プロダクトの核は「調査官の各判断（何を根拠に次へ掘るか）」を UI タイムラインへリアルタイム配信すること。ADK では判断理由が自由テキストイベントとして流れ、ツール呼び出しイベントとのペアリングとパースが必要になる。自前ループでは Gemini の structured output で `Decision(tool, args, reason)` をスキーマ保証付きで取得でき、そのまま SSE イベントになる
2. **テスト容易性**: 遡行ループの停止条件・証拠の重複排除・掘り先候補の管理はデモの安定性に直結するため TDD で実装した。LLM 判断を関数として注入する設計により、ループ自体を決定的にテストできる
3. **依存の軽さ**: ADK は依存 50 パッケージ超。Cloud Run のイメージサイズとコールドスタートに響く

**モデルの使い分け**: 調査官の毎ステップ判断は Gemini Flash（高頻度・低コスト）、史官の最終回答のみ Gemini Pro（1回・品質勝負）。環境変数 `EXCAVATOR_MODEL` / `HISTORIAN_MODEL` で差し替え可能。

**Vertex AI への移行**: `genai.Client` の初期化切替のみで移行可能（実運用では Workload Identity + Vertex AI を想定）。

## セットアップ

```bash
uv sync
cp .env.example .env  # GEMINI_API_KEY / GITHUB_TOKEN を設定
uv run pytest
```

## 今後の拡張

- 評価パイプライン（evals/）の Cloud Build CI 統合
- 予言モジュール Oracle: 削除 PR に過去の障害 Issue を引用した注意コメントを付与
