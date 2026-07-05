"""Web サーバ — 調査過程を SSE で流し、最後に史官の回答を届ける。

Day 1: プレースホルダ UI + /api/dig (SSE)。Day 2 に React SPA が frontend/dist に載る。
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .excavator import Excavator
from .github_tools import GitHubToolbox
from .historian import Historian
from .llm import GeminiAgents
from .models import EvidenceChain

load_dotenv()
app = FastAPI(title="Code Archaeologist")

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

_PLACEHOLDER = """<!doctype html>
<meta charset="utf-8">
<title>Code Archaeologist</title>
<style>body{font-family:system-ui;max-width:640px;margin:4rem auto;line-height:1.7}</style>
<h1>🏺 Code Archaeologist</h1>
<p>「なぜこのコードはこうなっているのか?」に、証拠付きで答えるエージェント。</p>
<p>Web UI は建設中（Day 2）。API は稼働中:</p>
<pre>GET /api/dig?repo=owner/name&amp;path=src/api.py&amp;line=42&amp;q=なぜ?</pre>
"""


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


# /healthz は Google Frontend の予約パスでエッジに横取りされるため /api/health を使う
@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/dig")
def dig(repo: str, path: str, line: int, q: str):
    if "/" not in repo:
        raise HTTPException(400, "repo は owner/name 形式で指定してください")
    owner, name = repo.split("/", 1)
    agents = GeminiAgents()
    excavator = Excavator(
        toolbox=GitHubToolbox(token=os.environ["GITHUB_TOKEN"]),
        decide=agents.decide,
    )

    def stream():
        chain = EvidenceChain()
        try:
            for event in excavator.dig(owner, name, path, line, q):
                if event.type == "done":
                    chain = EvidenceChain.model_validate(event.payload["chain"])
                yield _sse(event.model_dump())
            answer = Historian(agents.generate).narrate(q, chain)
            yield _sse({"type": "answer", "payload": answer.model_dump()})
        except Exception as exc:  # SSE は途中で HTTP エラーを返せないためイベントで通知
            yield _sse({"type": "error", "payload": {"message": str(exc)}})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
else:

    @app.get("/", response_class=HTMLResponse)
    def placeholder() -> str:
        return _PLACEHOLDER
