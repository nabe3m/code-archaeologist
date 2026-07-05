import { useEffect, useRef } from "react";

interface Props {
  code: string | null;
  path: string;
  highlightLine: number;
  started: boolean;
}

export function CodePane({ code, path, highlightLine, started }: Props) {
  const highlightRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    highlightRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [code, highlightLine]);

  return (
    <section className="pane code-pane" aria-label="対象コード">
      <div className="pane-title">
        <span className="pane-icon">📄</span>
        {path}
        <span className="line-badge">L{highlightLine}</span>
      </div>
      <div className="code-scroll">
        {!started ? (
          <p className="placeholder">質問を入力して「発掘する」を押すと、対象コードがここに表示されます</p>
        ) : code === null ? (
          <p className="placeholder">コードを取得中…</p>
        ) : code === "" ? (
          <p className="placeholder">コードを取得できませんでした（リポジトリ/パスを確認してください）</p>
        ) : (
          <pre className="code">
            {code.split("\n").map((text, i) => {
              const line = i + 1;
              const highlighted = line === highlightLine;
              return (
                <div
                  key={line}
                  ref={highlighted ? highlightRef : undefined}
                  className={highlighted ? "code-line highlight" : "code-line"}
                >
                  <span className="line-number">{line}</span>
                  <span className="line-text">{text || " "}</span>
                </div>
              );
            })}
          </pre>
        )}
      </div>
    </section>
  );
}
