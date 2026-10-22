import { useEffect, useMemo, useState } from "react";

type N = { id: string; label: string; kind: string; col: number; status?: string; source?: string };
type E = { from: string; to: string; label: string; tier: string; kind: string };
export type Graph = { nodes: N[]; edges: E[] };

const VIEWS: { kind: string; title: string; blurb: string }[] = [
  { kind: "injury", title: "Injury rules", blurb: "Each exercise left out for an injury, through the load it puts on a structure, up the part-of hierarchy to the condition and the rule." },
  { kind: "picked", title: "Why these were picked", blurb: "The exercises in the plan, with the graph paths that allowed or recommended them." },
  { kind: "family", title: "Exercise family", blurb: "Exercises left out because they are a variant of an excluded family." },
  { kind: "equipment", title: "Equipment", blurb: "Exercises left out because something they require is not available today." },
];
const COLS = ["Exercise", "Loads or needs", "Anatomy (part-of)", "Condition", "Rule"];
const TIER = { exclude: "var(--color-excl)", downrank: "var(--color-mod)", allow: "var(--color-spot)", uprank: "var(--color-ok)" } as Record<string, string>;
const ROW = 28, NODE_H = 20, TOP = 26;

export default function PathGraph({ graph }: { graph: Graph }) {
  const present = VIEWS.filter((v) => graph.edges.some((e) => e.kind === v.kind));
  const [view, setView] = useState(present[0]?.kind);
  const [big, setBig] = useState(false);
  useEffect(() => {
    if (!big) return;
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setBig(false);
    addEventListener("keydown", esc);
    return () => removeEventListener("keydown", esc);
  }, [big]);

  if (!present.length) return null;
  const v = VIEWS.find((x) => x.kind === view)!;
  const edges = graph.edges.filter((e) => e.kind === view);
  const ids = new Set(edges.flatMap((e) => [e.from, e.to]));

  return (
    <section className={big ? "fixed inset-0 z-50 overflow-auto bg-chalk p-6" : "mt-1"} aria-modal={big || undefined} role={big ? "dialog" : undefined}>
      <div className="flex flex-wrap items-center gap-1.5" role="tablist" aria-label="Graph view">
        {present.map((p) => {
          const n = new Set(graph.edges.filter((e) => e.kind === p.kind).map((e) => e.from).filter((f) => f.startsWith("x:"))).size;
          return (
            <button key={p.kind} role="tab" aria-selected={view === p.kind} onClick={() => setView(p.kind)}
              className={`rounded-full px-2.5 py-1 text-xs ${view === p.kind ? "bg-ink text-white" : "border border-rule bg-card text-iron hover:border-spot"}`}>
              {p.title} · {n}
            </button>
          );
        })}
        <button onClick={() => setBig(!big)} className="ml-auto rounded-md border border-rule bg-card px-2.5 py-1 text-xs text-iron hover:border-spot">
          {big ? "Close (Esc)" : "Expand"}
        </button>
      </div>
      <p className="mt-1.5 text-sm text-iron">{v.blurb} Hover or focus a node to trace its path.</p>
      <Layered key={view} title={v.title} nodes={graph.nodes.filter((n) => ids.has(n.id))} edges={edges} cols={COLS} big={big} />
      <Legend />
    </section>
  );
}

export function Legend() {
  return (
    <p className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-xs text-iron">
      {[["exclude", "left out"], ["downrank", "kept lower, with a cue"], ["allow", "allowed or in the plan"], ["uprank", "recommended"]].map(([t, l]) => (
        <span key={t} className="inline-flex items-center gap-1.5"><span className="inline-block h-0.5 w-4" style={{ background: TIER[t] }} />{l}</span>
      ))}
    </p>
  );
}

const KIND_TONE: Record<string, string> = {
  member: "var(--color-ink)", injury: "var(--color-mod)", goal: "var(--color-ok)", condition: "var(--color-excl)",
};

// Draws any small column-ordered graph: hover or focus a node to light everything connected to it.
export function Layered({ nodes, edges, cols, title, big = false, widths, maxH = 460 }:
  { nodes: N[]; edges: E[]; cols: string[]; title: string; big?: boolean; widths?: number[]; maxH?: number }) {
  const [hover, setHover] = useState<string | null>(null);
  const g = useMemo(() => layout(nodes, edges, big, widths), [nodes, edges, big, widths]);
  const lit = useMemo(() => (hover ? connected(edges, hover) : null), [edges, hover]);
  return (
    <div className="mt-2 overflow-auto rounded-md border border-rule bg-card" style={big ? undefined : { maxHeight: maxH }}>
      <svg viewBox={`0 0 ${g.w} ${g.h}`} width={g.w} height={g.h} className="block" role="img"
        aria-label={`${title}: ${nodes.length} graph nodes and ${edges.length} edges`}>
        {g.cols.map((c, i) => (
          <text key={c} x={g.x[i] + 2} y={16} fontSize={10.5} fontWeight={600} fill="var(--color-iron)">{cols[c].toUpperCase()}</text>
        ))}
        {edges.map((e, i) => {
          const a = g.pos[e.from], b = g.pos[e.to];
          const x1 = a.x + g.wOf(e.from), y1 = a.y + NODE_H / 2, x2 = b.x, y2 = b.y + NODE_H / 2, mx = (x1 + x2) / 2;
          const on = !lit || (lit.has(e.from) && lit.has(e.to));
          return (
            <path key={i} d={`M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`} fill="none"
              stroke={TIER[e.tier] ?? TIER.allow} strokeWidth={on && lit ? 2 : 1.3} opacity={on ? 0.75 : 0.08}>
              <title>{`${e.label} (${e.tier})`}</title>
            </path>
          );
        })}
        {nodes.map((n) => {
          const p = g.pos[n.id];
          const on = !lit || lit.has(n.id);
          const tone = n.kind === "exercise" ? TIER[n.status === "chosen" ? "allow" : n.status!] ?? TIER.allow : KIND_TONE[n.kind] ?? "var(--color-iron)";
          const dot = n.kind === "exercise" || n.kind in KIND_TONE;
          return (
            <g key={n.id} transform={`translate(${p.x},${p.y})`} opacity={on ? 1 : 0.25} tabIndex={0}
              onMouseEnter={() => setHover(n.id)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(n.id)} onBlur={() => setHover(null)}
              style={{ cursor: "default", outline: "none" }}>
              <title>{n.label}{n.source ? `\n${n.source}` : ""}</title>
              <rect width={g.wOf(n.id)} height={NODE_H} rx={NODE_H / 2} fill={dot ? "var(--color-card)" : "var(--color-chalk)"}
                stroke={tone} strokeWidth={hover === n.id ? 2 : 1} />
              {dot && <circle cx={10} cy={NODE_H / 2} r={3.5} fill={tone} />}
              <text x={dot ? 18 : 9} y={14} fontSize={11.5} fill="var(--color-ink)">{clip(n.label, g.wOf(n.id))}</text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function clip(s: string, w: number) {
  const max = Math.floor((w - 22) / 6.2);
  return s.length > max ? s.slice(0, max - 1) + "…" : s;
}

// Everything reachable upstream and downstream of one node, so a hover lights the whole path.
function connected(edges: E[], start: string) {
  const seen = new Set([start]);
  for (const dir of ["down", "up"] as const) {
    const stack = [start];
    while (stack.length) {
      const id = stack.pop()!;
      for (const e of edges) {
        const [a, b] = dir === "down" ? [e.from, e.to] : [e.to, e.from];
        if (a === id && !seen.has(b)) { seen.add(b); stack.push(b); }
      }
    }
  }
  return seen;
}

const KIND_ORDER = ["injury", "load", "goal", "muscle", "family", "equipment", "activity"];
const kindRank = (n: N) => (KIND_ORDER.indexOf(n.kind) + 1 || 99);

// Columns left to right; rows ordered so each column follows its neighbours on the left (one barycentre sweep).
function layout(nodes: N[], edges: E[], big: boolean, widths?: number[]) {
  const cols = [...new Set(nodes.map((n) => n.col))].sort();
  const byCol = cols.map((c) => nodes.filter((n) => n.col === c));
  const rank: Record<string, number> = {};
  byCol[1]?.sort((a, b) => kindRank(a) - kindRank(b) || a.label.localeCompare(b.label)).forEach((n, i) => (rank[n.id] = i));
  const avg = (n: N, dir: "from" | "to") => {
    const r = edges.filter((e) => e[dir] === n.id).map((e) => rank[dir === "from" ? e.to : e.from]).filter((x) => x !== undefined);
    return r.length ? r.reduce((s, x) => s + x, 0) / r.length : 1e9;
  };
  byCol[0]?.sort((a, b) => avg(a, "from") - avg(b, "from") || a.label.localeCompare(b.label)).forEach((n, i) => (rank[n.id] = i));
  for (const col of byCol.slice(2)) col.sort((a, b) => avg(a, "to") - avg(b, "to")).forEach((n, i) => (rank[n.id] = i));

  const gap = big ? 48 : 30, k = big ? 1.4 : 1;
  const wd = cols.map((c) => k * (widths?.[c] ?? (c === 0 ? 190 : 150))); // exercise names need the wider first column
  const x = wd.map((_, i) => wd.slice(0, i).reduce((s, w) => s + w + gap, 0));
  const rows = Math.max(...byCol.map((c) => c.length));
  const h = TOP + rows * ROW + 4;
  const pos: Record<string, { x: number; y: number }> = {};
  byCol.forEach((col, i) => {
    const off = ((rows - col.length) * ROW) / 2; // centre short columns against the tallest
    col.forEach((n, r) => (pos[n.id] = { x: x[i], y: TOP + off + r * ROW }));
  });
  const colOf = Object.fromEntries(nodes.map((n) => [n.id, cols.indexOf(n.col)]));
  const wOf = (id: string) => wd[colOf[id]];
  return { cols, x, pos, w: x[x.length - 1] + wd[wd.length - 1] + 2, h, wOf };
}
