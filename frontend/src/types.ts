// バックエンドの DigEvent / Answer と対応する型（models.py / historian.py 参照）

export type DigEvent =
  | { type: "dig_started"; payload: { question: string; target: Target } }
  | { type: "dig_decision"; payload: { tool: string; args: Record<string, unknown>; reason: string } }
  | { type: "evidence_found"; payload: { evidence: Evidence } }
  | { type: "error"; payload: { tool?: string; message: string } }
  | { type: "done"; payload: { steps: number; evidence_count: number; stopped_by: string } }
  | { type: "answer"; payload: Answer };

export interface Target {
  owner: string;
  repo: string;
  path: string;
  line: number;
}

export interface Evidence {
  kind: string;
  ref: string;
  url: string;
  title: string;
  detail: string;
  author: string;
  date: string;
}

export interface Source {
  n: number;
  label: string;
  url: string;
  title: string;
}

export interface Answer {
  text: string;
  sources: Source[];
}

export interface DigRequest {
  repo: string;
  path: string;
  line: number;
  question: string;
}
