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

（ADK スパイクの結果を含め、Day 1 に記載）

## セットアップ

```bash
uv sync
cp .env.example .env  # GEMINI_API_KEY / GITHUB_TOKEN を設定
uv run pytest
```

## 今後の拡張

- 評価パイプライン（evals/）の Cloud Build CI 統合
- 予言モジュール Oracle: 削除 PR に過去の障害 Issue を引用した注意コメントを付与
