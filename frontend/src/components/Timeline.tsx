import { useEffect, useRef } from "react";
import type { DigEvent } from "../types";

interface Props {
  events: DigEvent[];
  phase: "idle" | "digging" | "done" | "failed";
}

const TOOL_LABELS: Record<string, string> = {
  blame_line: "git blame",
  get_commit: "コミットを読む",
  get_pr: "PR 議論を読む",
  get_issue: "Issue を読む",
  finish: "調査終了",
};

const KIND_LABELS: Record<string, string> = {
  blame: "blame",
  commit: "コミット",
  pull_request: "PR",
  pr_comment: "PR コメント",
  issue: "Issue",
  issue_comment: "Issue コメント",
};

function Entry({ event }: { event: DigEvent }) {
  switch (event.type) {
    case "dig_started":
      return (
        <li className="entry started">
          <span className="entry-icon">🏺</span>
          <div>
            <div className="entry-title">調査開始</div>
            <div className="entry-body">{event.payload.question}</div>
          </div>
        </li>
      );
    case "dig_decision":
      return (
        <li className="entry decision">
          <span className="entry-icon">🤔</span>
          <div>
            <div className="entry-title">
              調査官の判断
              <span className="tool-badge">{TOOL_LABELS[event.payload.tool] ?? event.payload.tool}</span>
            </div>
            <div className="entry-body">{event.payload.reason}</div>
          </div>
        </li>
      );
    case "evidence_found": {
      const e = event.payload.evidence;
      return (
        <li className="entry evidence">
          <span className="entry-icon">📜</span>
          <div>
            <div className="entry-title">
              証拠を発掘
              <span className="kind-badge">{KIND_LABELS[e.kind] ?? e.kind}</span>
            </div>
            <div className="entry-body">
              <a href={e.url} target="_blank" rel="noreferrer">
                {e.title}
              </a>
              <span className="entry-meta">
                {e.author} · {e.date.slice(0, 10)}
              </span>
            </div>
          </div>
        </li>
      );
    }
    case "error":
      return (
        <li className="entry error">
          <span className="entry-icon">⚠️</span>
          <div className="entry-body">{event.payload.message}</div>
        </li>
      );
    case "done":
      return (
        <li className="entry done">
          <span className="entry-icon">⛏️</span>
          <div className="entry-body">
            調査完了 — {event.payload.steps} ステップで証拠 {event.payload.evidence_count} 件を発掘。史官が回答を執筆中…
          </div>
        </li>
      );
    default:
      return null;
  }
}

export function Timeline({ events, phase }: Props) {
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events.length]);

  return (
    <section className="pane timeline-pane" aria-label="調査タイムライン" aria-live="polite">
      <div className="pane-title">
        <span className="pane-icon">🔍</span>
        調査タイムライン
        {phase === "digging" ? <span className="pulse" aria-label="調査中" /> : null}
      </div>
      <div className="timeline-scroll">
        {events.length === 0 ? (
          <p className="placeholder">
            {phase === "failed"
              ? "調査を開始できませんでした。接続とパラメータを確認してください。"
              : "調査官の遡行判断がここにリアルタイムで流れます"}
          </p>
        ) : (
          <ol className="timeline">
            {events.map((event, i) => (
              <Entry key={i} event={event} />
            ))}
          </ol>
        )}
        <div ref={endRef} />
      </div>
    </section>
  );
}
