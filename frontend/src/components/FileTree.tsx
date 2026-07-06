import { useMemo, useState } from "react";

interface Props {
  paths: string[] | null;
  selected: string;
  onSelect: (path: string) => void;
}

interface DirNode {
  dirs: Map<string, DirNode>;
  files: string[]; // full paths
}

function buildTree(paths: string[]): DirNode {
  const root: DirNode = { dirs: new Map(), files: [] };
  for (const path of paths) {
    const parts = path.split("/");
    let node = root;
    for (const part of parts.slice(0, -1)) {
      if (!node.dirs.has(part)) {
        node.dirs.set(part, { dirs: new Map(), files: [] });
      }
      node = node.dirs.get(part)!;
    }
    node.files.push(path);
  }
  return root;
}

function Dir({
  name,
  node,
  depth,
  selected,
  onSelect,
}: {
  name: string;
  node: DirNode;
  depth: number;
  selected: string;
  onSelect: (path: string) => void;
}) {
  const [open, setOpen] = useState(true);
  return (
    <>
      <button
        type="button"
        className="tree-row tree-dir"
        style={{ paddingLeft: 8 + depth * 14 }}
        onClick={() => setOpen((o) => !o)}
      >
        {open ? "▾" : "▸"} 📁 {name}
      </button>
      {open ? <Children node={node} depth={depth + 1} selected={selected} onSelect={onSelect} /> : null}
    </>
  );
}

function Children({
  node,
  depth,
  selected,
  onSelect,
}: {
  node: DirNode;
  depth: number;
  selected: string;
  onSelect: (path: string) => void;
}) {
  return (
    <>
      {[...node.dirs.entries()].map(([name, child]) => (
        <Dir key={name} name={name} node={child} depth={depth} selected={selected} onSelect={onSelect} />
      ))}
      {node.files.map((path) => {
        const name = path.split("/").pop();
        return (
          <button
            type="button"
            key={path}
            className={path === selected ? "tree-row tree-file active" : "tree-row tree-file"}
            style={{ paddingLeft: 8 + depth * 14 }}
            onClick={() => onSelect(path)}
            title={path}
          >
            📄 {name}
          </button>
        );
      })}
    </>
  );
}

export function FileTree({ paths, selected, onSelect }: Props) {
  const tree = useMemo(() => (paths ? buildTree(paths) : null), [paths]);
  return (
    <section className="pane tree-pane" aria-label="ファイルツリー">
      <div className="pane-title">
        <span className="pane-icon">🗂️</span>
        ファイル
      </div>
      <div className="tree-scroll">
        {tree === null ? (
          <p className="placeholder">リポジトリを読み込むとファイル一覧が表示されます</p>
        ) : (
          <Children node={tree} depth={0} selected={selected} onSelect={onSelect} />
        )}
      </div>
    </section>
  );
}
