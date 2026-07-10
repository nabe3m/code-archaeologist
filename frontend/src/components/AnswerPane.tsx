import type { Answer, Prophecy, Verdict } from "../types";
import type { AuditResult } from "../App";

interface Props {
  answer: Answer | null;
  auditResults: AuditResult[];
  mode: "dig" | "audit";
  phase: "idle" | "digging" | "done" | "failed" | "stopped";
}

/** 回答本文中の [n] を対応する出典へのリンクに変換して描画する */
function CitedText({ text, answer }: { text: string; answer: Answer }) {
  const parts = text.split(/(\[\d+\])/);
  return (
    <>
      {parts.map((part, i) => {
        const match = part.match(/^\[(\d+)\]$/);
        const source = match ? answer.sources.find((s) => s.n === Number(match[1])) : undefined;
        return source ? (
          <a key={i} className="citation" href={source.url} target="_blank" rel="noreferrer" title={source.title}>
            {part}
          </a>
        ) : (
          <span key={i}>{part}</span>
        );
      })}
    </>
  );
}

function OracleNote({ oracle }: { oracle: Prophecy }) {
  return (
    <div className="oracle-note">
      <p className="oracle-title">🔮 Oracle の予言 — このコードが守っていた障害</p>
      <p>{oracle.guarded_incident}</p>
      <p>
        <strong>再発の兆候:</strong> {oracle.recurrence_symptoms}
      </p>
      <p>
        <strong>対処:</strong> {oracle.rollback_hint}
      </p>
      <a href={oracle.comment_url} target="_blank" rel="noreferrer">
        PR に投稿された予言コメントを見る →
      </a>
    </div>
  );
}

function DigResult({ answer, phase }: { answer: Answer | null; phase: Props["phase"] }) {
  if (answer === null) {
    return (
      <p className="placeholder">
        {phase === "digging"
          ? "証拠が揃い次第、出典リンク付きの回答がここに表示されます"
          : phase === "stopped"
            ? "調査を停止しました"
            : "—"}
      </p>
    );
  }
  return (
    <div className="answer">
      <div className="answer-text">
        <CitedText text={answer.text} answer={answer} />
      </div>
      {answer.sources.length > 0 ? (
        <div className="sources">
          <div className="sources-title">出典</div>
          <ol>
            {answer.sources.map((s) => (
              <li key={s.n} value={s.n}>
                <a href={s.url} target="_blank" rel="noreferrer">
                  {s.label} — {s.title}
                </a>
              </li>
            ))}
          </ol>
        </div>
      ) : null}
    </div>
  );
}

function VerdictCard({ verdict, prUrl, oracle }: { verdict: Verdict; prUrl: string | null; oracle: Prophecy | null }) {
  return (
    <div className="verdict-card">
      <p className="verdict-badge-row">
        <span className={verdict.expired ? "verdict-badge expired" : "verdict-badge valid"}>
          {verdict.expired ? "⚖️ 理由が失効 — 削除可能" : "⚖️ 現在も有効 — 維持すべき"}
        </span>
        <code>
          L{verdict.candidate.line}: {verdict.candidate.snippet}
        </code>
      </p>
      <p>{verdict.justification}</p>
      {verdict.expired ? (
        prUrl ? (
          <a className="pr-link" href={prUrl} target="_blank" rel="noreferrer">
            🎉 削除 PR を自動作成しました → {prUrl.replace("https://github.com/", "")}
          </a>
        ) : (
          <p className="placeholder">削除 PR を作成中…</p>
        )
      ) : (
        <p className="keep-note">このコードの前提はまだ生きています。削除 PR は作成しません。</p>
      )}
      {oracle ? <OracleNote oracle={oracle} /> : null}
    </div>
  );
}

function AuditResults({ results, phase }: { results: AuditResult[]; phase: Props["phase"] }) {
  if (results.length === 0) {
    return (
      <p className="placeholder">
        {phase === "digging"
          ? "防御的コードを検出し、歴史を発掘して1件ずつ判決を下します"
          : phase === "stopped"
            ? "監査を停止しました"
            : "—"}
      </p>
    );
  }
  return (
    <div className="verdict-list">
      {results.map((r, i) => (
        <VerdictCard key={i} verdict={r.verdict} prUrl={r.prUrl} oracle={r.oracle} />
      ))}
      {phase === "digging" ? <p className="placeholder">次の候補を監査中…</p> : null}
    </div>
  );
}

export function AnswerPane({ answer, auditResults, mode, phase }: Props) {
  return (
    <section className="pane answer-pane" aria-label="結果">
      <div className="pane-title">
        <span className="pane-icon">📜</span>
        {mode === "audit" ? "監査官の判決" : "史官の回答"}
      </div>
      {mode === "audit" ? (
        <AuditResults results={auditResults} phase={phase} />
      ) : (
        <DigResult answer={answer} phase={phase} />
      )}
    </section>
  );
}
