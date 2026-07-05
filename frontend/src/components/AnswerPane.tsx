import type { Answer } from "../types";

interface Props {
  answer: Answer | null;
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

export function AnswerPane({ answer, phase }: Props) {
  return (
    <section className="pane answer-pane" aria-label="史官の回答">
      <div className="pane-title">
        <span className="pane-icon">📜</span>
        史官の回答
      </div>
      {answer === null ? (
        <p className="placeholder">
          {phase === "digging" ? "証拠が揃い次第、出典リンク付きの回答がここに表示されます" : "—"}
        </p>
      ) : (
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
      )}
    </section>
  );
}
