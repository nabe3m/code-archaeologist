import { useCallback, useEffect, useRef, useState } from "react";
import type { Answer, DigEvent, Prophecy, Verdict } from "./types";
import { CodePane } from "./components/CodePane";
import { FileTree } from "./components/FileTree";
import { Timeline } from "./components/Timeline";
import { AnswerPane } from "./components/AnswerPane";

type Phase = "idle" | "digging" | "done" | "failed" | "stopped";
type Mode = "dig" | "audit";

export interface AuditResult {
  verdict: Verdict;
  prUrl: string | null;
  oracle: Prophecy | null;
}

const DEMO = {
  repo: "nabe3m/demo-repo",
  path: "orders/api.py",
  lineSpec: "15",
  question: "この sleep(3) はなぜあるの? 今も必要?",
};

/** "14" | "14-16" → [14, null] | [14, 16] */
function parseLineSpec(spec: string): [number, number | null] {
  const match = spec.trim().match(/^(\d+)(?:\s*-\s*(\d+))?$/);
  if (!match) return [1, null];
  const start = Number(match[1]);
  const end = match[2] ? Number(match[2]) : null;
  return end && end > start ? [start, end] : [start, null];
}

export default function App() {
  const [repo, setRepo] = useState(DEMO.repo);
  const [path, setPath] = useState(DEMO.path);
  const [lineSpec, setLineSpec] = useState(DEMO.lineSpec);
  const [question, setQuestion] = useState(DEMO.question);

  const [treePaths, setTreePaths] = useState<string[] | null>(null);
  const [code, setCode] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [mode, setMode] = useState<Mode>("dig");
  const [events, setEvents] = useState<DigEvent[]>([]);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [auditResults, setAuditResults] = useState<AuditResult[]>([]);
  const sourceRef = useRef<EventSource | null>(null);
  const gotResultRef = useRef(false);

  const [selStart, selEnd] = parseLineSpec(lineSpec);

  const openFile = useCallback((targetRepo: string, targetPath: string) => {
    setPath(targetPath);
    setCode(null);
    fetch(
      `/api/file?repo=${encodeURIComponent(targetRepo)}&path=${encodeURIComponent(targetPath)}`,
    )
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))))
      .then((d: { content: string }) => setCode(d.content))
      .catch(() => setCode(""));
  }, []);

  const loadRepo = useCallback(
    (targetRepo: string, targetPath?: string) => {
      setTreePaths(null);
      fetch(`/api/tree?repo=${encodeURIComponent(targetRepo)}`)
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))))
        .then((d: { paths: string[] }) => {
          setTreePaths(d.paths);
          const initial = targetPath && d.paths.includes(targetPath) ? targetPath : d.paths[0];
          if (initial) openFile(targetRepo, initial);
        })
        .catch(() => setTreePaths([]));
    },
    [openFile],
  );

  // 初回はデモ用リポジトリをエディタとして開いておく
  useEffect(() => {
    loadRepo(DEMO.repo, DEMO.path);
  }, [loadRepo]);

  const selectLine = useCallback((line: number, extend: boolean) => {
    setLineSpec((prev) => {
      if (!extend) return String(line);
      const [start] = parseLineSpec(prev);
      const [a, b] = line < start ? [line, start] : [start, line];
      return a === b ? String(a) : `${a}-${b}`;
    });
  }, []);

  const start = useCallback(
    (nextMode: Mode) => {
      sourceRef.current?.close();
      gotResultRef.current = false;
      setMode(nextMode);
      setPhase("digging");
      setEvents([]);
      setAnswer(null);
      setAuditResults([]);
      if (code === null) openFile(repo, path);

      const params = new URLSearchParams({ repo, path });
      if (nextMode === "dig") {
        params.set("line", String(selStart));
        if (selEnd) params.set("line_end", String(selEnd));
        params.set("q", question);
      }
      const source = new EventSource(
        nextMode === "dig" ? `/api/dig?${params}` : `/api/audit?${params}`,
      );
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
            // 監査候補の行をエディタでハイライト
            setLineSpec(String(event.payload.line));
            break;
          case "verdict":
            // 監査は複数候補を順に処理するため、判決は一覧に積む
            setAuditResults((prev) => [...prev, { verdict: event.payload, prUrl: null, oracle: null }]);
            gotResultRef.current = true;
            break;
          case "pr_created":
            setAuditResults((prev) =>
              prev.map((r, i) =>
                i === prev.length - 1 ? { ...r, prUrl: event.payload.url } : r,
              ),
            );
            break;
          case "oracle":
            setAuditResults((prev) =>
              prev.map((r, i) =>
                i === prev.length - 1 ? { ...r, oracle: event.payload } : r,
              ),
            );
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
    [repo, path, code, question, selStart, selEnd, openFile],
  );

  const stop = useCallback(() => {
    sourceRef.current?.close();
    setPhase("stopped");
  }, []);

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
          <div className="repo-group">
            <input
              className="input repo"
              value={repo}
              onChange={(e) => setRepo(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  loadRepo(repo);
                }
              }}
              placeholder="owner/repo"
              aria-label="リポジトリ"
              required
            />
            <button type="button" className="open-button" onClick={() => loadRepo(repo)}>
              開く
            </button>
          </div>
          <input
            className="input line"
            value={lineSpec}
            onChange={(e) => setLineSpec(e.target.value)}
            placeholder="14 or 14-16"
            aria-label="行または行範囲"
            title="行番号クリックで選択、Shift+クリックで範囲選択"
            required
          />
          <input
            className="input question"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
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
          {digging ? (
            <button
              className="stop-button"
              type="button"
              title="実行中の調査を中断します"
              onClick={stop}
            >
              ⏹ 停止
            </button>
          ) : null}
        </form>
      </header>

      <main className="panes">
        <FileTree paths={treePaths} selected={path} onSelect={(p) => openFile(repo, p)} />
        <CodePane
          code={code}
          path={path}
          highlightStart={selStart}
          highlightEnd={selEnd ?? selStart}
          onLineClick={selectLine}
        />
        <Timeline events={events} phase={phase} />
      </main>

      <AnswerPane answer={answer} auditResults={auditResults} mode={mode} phase={phase} />
    </div>
  );
}
