import { useCallback, useRef, useState } from "react";
import type { Answer, DigEvent, DigRequest } from "./types";
import { CodePane } from "./components/CodePane";
import { Timeline } from "./components/Timeline";
import { AnswerPane } from "./components/AnswerPane";

type Phase = "idle" | "digging" | "done" | "failed";

const DEMO: DigRequest = {
  repo: "nabe3m/code-archaeologist",
  path: "src/code_archaeologist/excavator.py",
  line: 30,
  question: "この decide 関数はなぜ注入式になっているの?",
};

export default function App() {
  const [form, setForm] = useState<DigRequest>(DEMO);
  const [phase, setPhase] = useState<Phase>("idle");
  const [events, setEvents] = useState<DigEvent[]>([]);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [code, setCode] = useState<string | null>(null);
  const [target, setTarget] = useState<DigRequest>(DEMO);
  const sourceRef = useRef<EventSource | null>(null);

  const dig = useCallback(() => {
    sourceRef.current?.close();
    setPhase("digging");
    setEvents([]);
    setAnswer(null);
    setCode(null);
    setTarget(form);

    // コード取得と調査開始を並行に（ウォーターフォール回避）
    fetch(`/api/file?repo=${encodeURIComponent(form.repo)}&path=${encodeURIComponent(form.path)}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))))
      .then((d: { content: string }) => setCode(d.content))
      .catch(() => setCode(""));

    const params = new URLSearchParams({
      repo: form.repo,
      path: form.path,
      line: String(form.line),
      q: form.question,
    });
    const source = new EventSource(`/api/dig?${params}`);
    sourceRef.current = source;
    source.onmessage = (message) => {
      const event: DigEvent = JSON.parse(message.data);
      if (event.type === "answer") {
        setAnswer(event.payload);
        setPhase("done");
        source.close();
      } else {
        setEvents((prev) => [...prev, event]);
      }
    };
    source.onerror = () => {
      setPhase((p) => (p === "digging" ? "failed" : p));
      source.close();
    };
  }, [form]);

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
            dig();
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
            {digging ? "発掘中…" : "⛏️ 発掘する"}
          </button>
        </form>
      </header>

      <main className="panes">
        <CodePane code={code} path={target.path} highlightLine={target.line} started={phase !== "idle"} />
        <Timeline events={events} phase={phase} />
      </main>

      <AnswerPane answer={answer} phase={phase} />
    </div>
  );
}
