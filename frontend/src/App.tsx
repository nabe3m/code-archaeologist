import { useCallback, useRef, useState } from "react";
import type { Answer, DigEvent, DigRequest, Verdict } from "./types";
import { CodePane } from "./components/CodePane";
import { Timeline } from "./components/Timeline";
import { AnswerPane } from "./components/AnswerPane";

type Phase = "idle" | "digging" | "done" | "failed";
type Mode = "dig" | "audit";

const DEMO: DigRequest = {
  repo: "nabe3m/demo-repo",
  path: "orders/api.py",
  line: 14,
  question: "この sleep(3) はなぜあるの? 今も必要?",
};

export default function App() {
  const [form, setForm] = useState<DigRequest>(DEMO);
  const [phase, setPhase] = useState<Phase>("idle");
  const [mode, setMode] = useState<Mode>("dig");
  const [events, setEvents] = useState<DigEvent[]>([]);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [prUrl, setPrUrl] = useState<string | null>(null);
  const [code, setCode] = useState<string | null>(null);
  const [target, setTarget] = useState<DigRequest>(DEMO);
  const sourceRef = useRef<EventSource | null>(null);
  const gotResultRef = useRef(false);

  const start = useCallback(
    (nextMode: Mode) => {
      sourceRef.current?.close();
      gotResultRef.current = false;
      setMode(nextMode);
      setPhase("digging");
      setEvents([]);
      setAnswer(null);
      setVerdict(null);
      setPrUrl(null);
      setCode(null);
      setTarget(form);

      // コード取得と調査開始を並行に（ウォーターフォール回避）
      fetch(`/api/file?repo=${encodeURIComponent(form.repo)}&path=${encodeURIComponent(form.path)}`)
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))))
        .then((d: { content: string }) => setCode(d.content))
        .catch(() => setCode(""));

      const url =
        nextMode === "dig"
          ? `/api/dig?${new URLSearchParams({
              repo: form.repo,
              path: form.path,
              line: String(form.line),
              q: form.question,
            })}`
          : `/api/audit?${new URLSearchParams({ repo: form.repo, path: form.path })}`;
      const source = new EventSource(url);
      sourceRef.current = source;
      source.onmessage = (message) => {
        const event: DigEvent = JSON.parse(message.data);
        switch (event.type) {
          case "answer":
            setAnswer(event.payload);
            gotResultRef.current = true;
            setPhase("done");
            source.close();
            return;
          case "audit_candidate":
            // 監査候補の行をコードペインでハイライト
            setTarget((t) => ({ ...t, line: event.payload.line }));
            break;
          case "verdict":
            setVerdict(event.payload);
            gotResultRef.current = true;
            if (!event.payload.expired) {
              setPhase("done");
            }
            break;
          case "pr_created":
            setPrUrl(event.payload.url);
            setPhase("done");
            break;
        }
        setEvents((prev) => [...prev, event]);
      };
      source.onerror = () => {
        // ストリームが閉じた時点で結果（回答 or 判決）まで出ていれば正常終了
        setPhase((p) => (p === "digging" ? (gotResultRef.current ? "done" : "failed") : p));
        source.close();
      };
    },
    [form],
  );

  const digging = phase === "digging";

  return (
    <div className="app">
      <header className="header">
        <h1>
          🏺 Code Archaeologist
          <span className="tagline">「なぜこのコードはこうなっているのか?」に、証拠付きで答える</span>
        </h1>
        <form
          className="dig-form"
          onSubmit={(e) => {
            e.preventDefault();
            start("dig");
          }}
        >
          <input
            className="input repo"
            value={form.repo}
            onChange={(e) => setForm({ ...form, repo: e.target.value })}
            placeholder="owner/repo"
            aria-label="リポジトリ"
            required
          />
          <input
            className="input path"
            value={form.path}
            onChange={(e) => setForm({ ...form, path: e.target.value })}
            placeholder="path/to/file.py"
            aria-label="ファイルパス"
            required
          />
          <input
            className="input line"
            type="number"
            min={1}
            value={form.line}
            onChange={(e) => setForm({ ...form, line: Number(e.target.value) })}
            aria-label="行番号"
            required
          />
          <input
            className="input question"
            value={form.question}
            onChange={(e) => setForm({ ...form, question: e.target.value })}
            placeholder="このコードへの質問（例: なぜ sleep(3) があるの?）"
            aria-label="質問"
            required
          />
          <button className="dig-button" type="submit" disabled={digging}>
            {digging && mode === "dig" ? "発掘中…" : "⛏️ 発掘する"}
          </button>
          <button
            className="audit-button"
            type="button"
            disabled={digging}
            title="ファイル全体から理由が失効した防御的コードを検出し、証拠付き削除 PR を作成します"
            onClick={() => start("audit")}
          >
            {digging && mode === "audit" ? "監査中…" : "⚖️ 監査する"}
          </button>
        </form>
      </header>

      <main className="panes">
        <CodePane code={code} path={target.path} highlightLine={target.line} started={phase !== "idle"} />
        <Timeline events={events} phase={phase} />
      </main>

      <AnswerPane answer={answer} verdict={verdict} prUrl={prUrl} mode={mode} phase={phase} />
    </div>
  );
}
