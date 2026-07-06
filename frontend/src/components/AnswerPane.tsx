import type { Answer, Verdict } from "../types";

interface Props {
  answer: Answer | null;
  verdict: Verdict | null;
  prUrl: string | null;
  mode: "dig" | "audit";
  phase: "idle" | "digging" | "done" | "failed";
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

function DigResult({ answer, phase }: { answer: Answer | null; phase: Props["phase"] }) {
  if (answer === null) {
    return (
      <p className="placeholder">
        {phase === "digging" ? "証拠が揃い次第、出典リンク付きの回答がここに表示されます" : "—"}
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

function AuditResult({ verdict, prUrl, phase }: { verdict: Verdict | null; prUrl: string | null; phase: Props["phase"] }) {
  if (verdict === null) {
    return (
      <p className="placeholder">
        {phase === "digging"
          ? "防御的コードを検出し、歴史を発掘して判決を下します"
          : "—"}
      </p>
    );
  }
  return (
    <div className="answer">
      <div className="answer-text">
        <p className="verdict-badge-row">
          <span className={verdict.expired ? "verdict-badge expired" : "verdict-badge valid"}>
            {verdict.expired ? "⚖️ 理由が失効 — 削除可能" : "⚖️ 現在も有効"}
          </span>
          <code>{verdict.candidate.snippet}</code>
        </p>
        <p>{verdict.justification}</p>
      </div>
      <div className="sources">
        <div className="sources-title">アクション</div>
        {prUrl ? (
          <a className="pr-link" href={prUrl} target="_blank" rel="noreferrer">
            🎉 削除 PR を自動作成しました → {prUrl.replace("https://github.com/", "")}
          </a>
        ) : verdict.expired ? (
          <p className="placeholder">削除 PR を作成中…</p>
        ) : (
          <p>このコードは維持すべきです。削除 PR は作成しません。</p>
        )}
      </div>
    </div>
  );
}

export function AnswerPane({ answer, verdict, prUrl, mode, phase }: Props) {
  return (
    <section className="pane answer-pane" aria-label="結果">
      <div className="pane-title">
        <span className="pane-icon">📜</span>
        {mode === "audit" ? "監査官の判決" : "史官の回答"}
      </div>
      {mode === "audit" ? (
        <AuditResult verdict={verdict} prUrl={prUrl} phase={phase} />
      ) : (
        <DigResult answer={answer} phase={phase} />
      )}
    </section>
  );
}
