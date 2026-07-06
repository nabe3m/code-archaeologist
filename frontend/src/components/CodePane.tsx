import { useEffect, useRef } from "react";

interface Props {
  code: string | null;
  path: string;
  highlightStart: number;
  highlightEnd: number;
  onLineClick: (line: number, extend: boolean) => void;
}

export function CodePane({ code, path, highlightStart, highlightEnd, onLineClick }: Props) {
  const highlightRef = useRef<HTMLDivElement | null>(null);

  // コードが読み込まれたときだけ選択行へスクロール（クリックのたびには動かさない）
  useEffect(() => {
    highlightRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [code]);

  const rangeLabel =
    highlightEnd > highlightStart ? `L${highlightStart}-${highlightEnd}` : `L${highlightStart}`;

  return (
    <section className="pane code-pane" aria-label="対象コード">
      <div className="pane-title">
        <span className="pane-icon">📄</span>
        {path}
        <span className="line-badge">{rangeLabel}</span>
        <span className="hint">行番号クリックで選択 / Shift+クリックで範囲</span>
      </div>
      <div className="code-scroll">
        {code === null ? (
          <p className="placeholder">コードを取得中…</p>
        ) : code === "" ? (
          <p className="placeholder">コードを取得できませんでした（リポジトリ/パスを確認してください）</p>
        ) : (
          <pre className="code">
            {code.split("\n").map((text, i) => {
              const line = i + 1;
              const highlighted = line >= highlightStart && line <= highlightEnd;
              return (
                <div
                  key={line}
                  ref={line === highlightStart ? highlightRef : undefined}
                  className={highlighted ? "code-line highlight" : "code-line"}
                >
                  <button
                    type="button"
                    className="line-number"
                    onClick={(e) => onLineClick(line, e.shiftKey)}
                    title="クリックで選択 / Shift+クリックで範囲選択"
                  >
                    {line}
                  </button>
                  <span className="line-text">{text || " "}</span>
                </div>
              );
            })}
          </pre>
        )}
      </div>
    </section>
  );
}
