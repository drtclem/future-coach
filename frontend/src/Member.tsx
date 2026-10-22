import { useEffect, useState } from "react";
import { api } from "./api";
import { Layered, Legend } from "./PathGraph";

const STAGE_TEXT: Record<string, string> = {
  onboarding: "New member", building: "Building", established: "Established", "at-risk": "Slipping", rehab: "In rehab",
};

export function MemberCard({ m }: { m: any }) {
  const r = m.readiness;
  const churnTone = m.churn.level === "elevated" ? "text-excl" : m.churn.level === "moderate" ? "text-mod" : "text-ok";
  const weeks = m.adherence.completed_weeks.slice(-8);
  return (
    <div className="space-y-4 rounded-lg border border-rule bg-card p-4">
      <div>
        <h2 className="text-xl font-semibold">{m.profile.name}</h2>
        <p className="text-sm text-iron">{m.profile.age} · {m.profile.tier} · member since {m.profile.member_since}</p>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {m.journey.stages.map((s: string) => (
            <span key={s} className={`rounded-full px-2 py-0.5 text-xs ${s === "at-risk" ? "bg-excl-soft text-excl" : s === "rehab" ? "bg-mod-soft text-mod" : "bg-spot-soft text-spot"}`}>
              {STAGE_TEXT[s] ?? s}
            </span>
          ))}
        </div>
      </div>

      <Row label="Today">
        <ReadinessMeter cap={r.rpe_cap} level={r.level} />
        <span className="mt-1 block text-iron">{r.evidence.map((e: any) => e.text).join("; ")}</span>
        {r.flags.map((f: string) => <span key={f} className="mt-1 block rounded bg-mod-soft px-2 py-1 text-mod">{f}</span>)}
      </Row>

      {m.sleep && (
        <Row label="Sleep, 14 nights (device)">
          <Spark values={m.sleep.series[0].values} labels={m.sleep.x} goal={m.sleep.goal} unit="h" />
          {r.sleep_source?.includes("check-in") && (
            <span className="block text-xs text-iron">Today's check-in says {r.sleep_last_night} h, which is what sets today's readiness.</span>
          )}
        </Row>
      )}

      {weeks.length > 0 && (
        <Row label={`Adherence, last ${weeks.length} completed weeks`}>
          <Bars values={weeks.map((w: any) => w.pct)} labels={weeks.map((w: any) => w.week_of)} />
          {m.adherence.current_week && (
            <span className="block text-xs text-iron">Current week in progress ({m.adherence.current_week.days_elapsed} of 7 days), not counted.</span>
          )}
        </Row>
      )}

      {m.injuries.length > 0 && (
        <Row label="Injuries">
          {m.injuries.map((i: any) => (
            <details key={i.id} className="mb-1">
              <summary className="cursor-pointer">{i.label}, <b>{i.status}</b></summary>
              <ul className="ml-4 mt-1 list-disc text-iron">{i.how_read.map((h: string) => <li key={h}>{h}</li>)}</ul>
            </details>
          ))}
        </Row>
      )}

      <Row label="Risk of dropping off">
        <Churn c={m.churn} tone={churnTone} />
      </Row>

      <Row label="Equipment">{m.equipment_available.join(", ") || "none listed"}</Row>
    </div>
  );
}

// Plain-language names for the churn signals computed in app/member/signals.py.
const SIGNAL: Record<string, string> = {
  adherence: "Fewer sessions done", skips: "Skipped sessions", messages: "Reaching out less",
  "session length": "Shorter sessions than preferred", sleep: "Short on sleep",
};

function Churn({ c, tone }: { c: any; tone: string }) {
  const fired = c.evidence.filter((e: any) => e.points > 0);
  const quiet = c.evidence.filter((e: any) => !e.points);
  const max = c.max_score ?? 7;
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <b className={`capitalize ${tone}`}>{c.level}</b>
        <span className="text-iron">· {c.score} of {max} warning points</span>
      </div>
      <div className="flex gap-0.5" aria-hidden>
        {Array.from({ length: max }, (_, i) => (
          <span key={i} className={`h-1.5 flex-1 rounded-full ${i < c.score ? (c.level === "elevated" ? "bg-excl" : c.level === "moderate" ? "bg-mod" : "bg-ok") : "bg-rule"}`} />
        ))}
      </div>
      <p className="text-xs text-iron">How likely this member is to drift off and stop training. 4+ points is elevated, 2–3 moderate.</p>
      {fired.length > 0 && (
        <ul className="space-y-1.5">
          {fired.map((e: any) => (
            <li key={e.text} className="flex gap-2">
              <span className="mt-0.5 h-fit shrink-0 rounded bg-chalk px-1.5 text-xs font-semibold text-ink">+{e.points}</span>
              <span><b className="font-medium">{SIGNAL[e.signal] ?? e.signal}</b><span className="block text-xs text-iron">{e.text}</span></span>
            </li>
          ))}
        </ul>
      )}
      {quiet.length > 0 && (
        <details className="text-xs text-iron">
          <summary className="cursor-pointer">Checked, no warning ({quiet.length})</summary>
          <ul className="ml-4 mt-1 list-disc">{quiet.map((e: any) => <li key={e.text}>{e.text}</li>)}</ul>
        </details>
      )}
      {c.disagreement && <p className="rounded bg-mod-soft px-2 py-1 text-xs text-mod"><b>About the morning brief:</b> {c.disagreement}</p>}
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="text-sm">
      <h3 className="mb-0.5 text-base font-semibold text-iron">{label}</h3>
      <div>{children}</div>
    </div>
  );
}

// RPE cap as a three-step meter: 8 normal, 7 reduced, 6 low (see app/member/signals.py).
function ReadinessMeter({ cap, level }: { cap: number; level: string }) {
  const steps = [6, 7, 8];
  return (
    <div className="flex items-center gap-2">
      <div className="flex gap-1" aria-hidden>
        {steps.map((s) => <span key={s} className={`h-2 w-7 rounded-full ${s <= cap ? (cap === 8 ? "bg-ok" : cap === 7 ? "bg-mod" : "bg-excl") : "bg-rule"}`} />)}
      </div>
      <span>Readiness <b>{level}</b>, effort cap RPE {cap}</span>
    </div>
  );
}

function Spark({ values, labels, goal, unit }: { values: number[]; labels: string[]; goal?: number; unit: string }) {
  const w = 240, h = 56, pad = 4;
  const lo = Math.min(...values, goal ?? Infinity) - 0.5, hi = Math.max(...values, goal ?? -Infinity) + 0.5;
  const x = (i: number) => pad + (i * (w - 2 * pad)) / Math.max(values.length - 1, 1);
  const y = (v: number) => h - pad - ((v - lo) / (hi - lo)) * (h - 2 * pad);
  const last = values[values.length - 1];
  const below = values.filter((v) => goal !== undefined && v < goal).length;
  return (
    <figure>
      <svg viewBox={`0 0 ${w} ${h}`} width="100%" height={h} role="img"
        aria-label={`Sleep over ${values.length} nights, last ${last}${unit}${goal ? `, ${below} nights under ${goal}${unit}` : ""}`}>
        {goal !== undefined && <>
          <line x1={pad} x2={w - pad} y1={y(goal)} y2={y(goal)} stroke="var(--color-mod)" strokeDasharray="3 3" />
          <text x={pad} y={y(goal) - 3} fontSize={9} fill="var(--color-mod)">goal {goal}{unit}</text>
        </>}
        <polyline points={values.map((v, i) => `${x(i)},${y(v)}`).join(" ")} fill="none" stroke="var(--color-spot)" strokeWidth={2} strokeLinejoin="round" />
        {values.map((v, i) => (
          <circle key={i} cx={x(i)} cy={y(v)} r={i === values.length - 1 ? 3.5 : 2} fill={goal !== undefined && v < goal ? "var(--color-card)" : "var(--color-spot)"}
            stroke="var(--color-spot)" strokeWidth={1.5}><title>{`${labels[i]}: ${v}${unit}`}</title></circle>
        ))}
      </svg>
      <figcaption className="text-xs text-iron">Last night {last}{unit}{goal !== undefined && ` · ${below} of ${values.length} nights under goal (open dots)`}</figcaption>
    </figure>
  );
}

function Bars({ values, labels }: { values: number[]; labels: string[] }) {
  return (
    <div className="flex h-14 items-end gap-1" role="img" aria-label={`Adherence by week: ${values.map((v, i) => `${labels[i]} ${v}%`).join(", ")}`}>
      {values.map((v, i) => (
        <div key={i} title={`week of ${labels[i]}: ${v}%`} className="flex flex-1 flex-col items-center justify-end gap-0.5">
          <div className={`w-full rounded-t ${v >= 100 ? "bg-spot" : v >= 75 ? "bg-spot/60" : "bg-mod"}`} style={{ height: `${Math.max(v, 4) * 0.44}px` }} />
          <span className="text-[9px] leading-none text-iron">{labels[i].slice(5).replace("-", "/")}</span>
        </div>
      ))}
    </div>
  );
}

const MEMBER_COLS = ["Member", "Has (KG2)", "Domain concepts (KG1)", "Rules and parent anatomy"];
const MEMBER_W = [104, 180, 140, 150];

export function MemberGraph({ memberKey, rev }: { memberKey: string; rev: number }) {
  const [g, setG] = useState<any>(null);
  const [big, setBig] = useState(false);
  useEffect(() => { setG(null); api(`/members/${memberKey}/graph`).then(setG); }, [memberKey, rev]);
  useEffect(() => {
    if (!big) return;
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setBig(false);
    addEventListener("keydown", esc);
    return () => removeEventListener("keydown", esc);
  }, [big]);
  if (!g) return <p className="p-4 text-sm text-iron">Loading the member graph…</p>;
  return (
    <div className={big ? "fixed inset-0 z-50 overflow-auto bg-chalk p-6" : "rounded-lg border border-rule bg-card p-4"} role={big ? "dialog" : undefined} aria-modal={big || undefined}>
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="display text-xl font-semibold">Member graph</h2>
        <button onClick={() => setBig(!big)} className="rounded-md border border-rule bg-card px-2.5 py-1 text-xs text-iron hover:border-spot">{big ? "Close (Esc)" : "Expand"}</button>
      </div>
      <p className="text-sm text-iron">
        What the system knows about this member (KG2) and the domain concepts it links to (KG1), read live from the graph store with SPARQL.
        Injury rules are filtered to the injury's current stage. Hover a node to trace it.
      </p>
      <Layered title="Member graph" nodes={g.nodes} edges={g.edges} cols={MEMBER_COLS} widths={MEMBER_W} maxH={640} big={big} />
      <Legend />
    </div>
  );
}
