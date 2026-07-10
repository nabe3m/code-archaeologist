import { useEffect, useRef } from "react";
import type { DigEvent } from "../types";

interface Props {
  events: DigEvent[];
  phase: "idle" | "digging" | "done" | "failed" | "stopped";
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
      if (event.payload.tool === "finish") {
        // 調査終了は「過程の区切り」であって結論ではないため控えめに表示する
        // （結論は史官/監査官が全証拠から出す）
        return (
          <li className="entry finish">
            <span className="entry-icon">🔚</span>
            <div>
              <div className="entry-title">調査官が証拠収集を完了</div>
              <div className="entry-body dim">{event.payload.reason}</div>
            </div>
          </li>
        );
      }
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
            調査完了 — {event.payload.steps} ステップで証拠 {event.payload.evidence_count} 件を発掘
          </div>
        </li>
      );
    case "audit_candidate":
      return (
        <li className="entry decision">
          <span className="entry-icon">🔎</span>
          <div>
            <div className="entry-title">監査候補を検出</div>
            <div className="entry-body">
              <code>
                L{event.payload.line}: {event.payload.snippet}
              </code>
              <div>{event.payload.reason}</div>
            </div>
          </div>
        </li>
      );
    case "verdict":
      return (
        <li className="entry evidence">
          <span className="entry-icon">⚖️</span>
          <div>
            <div className="entry-title">判決</div>
            <div className="entry-body">
              {event.payload.expired ? "理由が失効 — 削除可能" : "現在も有効"}
            </div>
          </div>
        </li>
      );
    case "pr_created":
      return (
        <li className="entry evidence">
          <span className="entry-icon">🎉</span>
          <div className="entry-body">
            <a href={event.payload.url} target="_blank" rel="noreferrer">
              削除 PR #{event.payload.number} を作成しました
            </a>
          </div>
        </li>
      );
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
