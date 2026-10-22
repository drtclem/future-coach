import { useState } from "react";
import { api, apiStream } from "./api";
import Glyph from "./Glyph";
import PathGraph from "./PathGraph";

const EXAMPLES = [
  "Lower-body exercises that avoid aggravating a knee injury",
  "Full body, no deadlift variations",
  "She has no barbell, only dumbbells and a kettlebell. Upper body.",
];

export default function Generator({ memberKey, member }: { memberKey: string; member: any }) {
  const [prompt, setPrompt] = useState(EXAMPLES[0]);
  const [time, setTime] = useState<string>("");
  const [res, setRes] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [rated, setRated] = useState<string>("");

  async function run(p = prompt) {
    setBusy(true); setErr(""); setRated("");
    try { await apiStream(`/members/${memberKey}/generate/stream`, { prompt: p, time_min: time ? Number(time) : null }, setRes); }
    catch (e: any) { setErr(`Couldn't build the plan. ${e.message}`); }
    finally { setBusy(false); }
  }
  async function rate(rating: "up" | "down") {
    await api("/feedback", { request_id: res.trace.request_id, rating }); setRated(rating);
  }

  return (
    <div className="rounded-lg border border-rule bg-card">
      <form className="space-y-3 border-b border-rule p-4" onSubmit={(e) => { e.preventDefault(); run(); }}>
        <label htmlFor="prompt" className="display block text-xl font-semibold">Build a session for {member?.profile?.name?.split(" ")[0] ?? "…"}</label>
        <textarea id="prompt" value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={2}
          className="w-full resize-y rounded-md border border-rule bg-chalk p-3 text-base" />
        <div className="flex flex-wrap items-center gap-2">
          <label className="text-sm text-iron" htmlFor="time">Time</label>
          <select id="time" value={time} onChange={(e) => setTime(e.target.value)} className="rounded-md border border-rule bg-card px-2 py-1.5 text-sm">
            <option value="">Her usual</option>
            {[20, 30, 45, 60].map((t) => <option key={t} value={t}>{t} min</option>)}
          </select>
          <button disabled={busy} className="ml-auto rounded-md bg-spot px-4 py-2 font-medium text-white disabled:opacity-60">
            {busy ? (res?.draft ? "Refining…" : "Building…") : "Build session"}
          </button>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {EXAMPLES.map((e) => (
            <button type="button" key={e} onClick={() => { setPrompt(e); run(e); }}
              className="rounded-full border border-rule px-2.5 py-1 text-xs text-iron hover:border-spot hover:text-spot">{e}</button>
          ))}
        </div>
      </form>

      {err && <p role="alert" className="m-4 rounded bg-excl-soft p-3 text-sm text-excl">{err}</p>}
      {!res && !err && <p className="p-4 text-sm text-iron">Describe the session in your own words. Safety rules are checked before anything is suggested.</p>}

      {res?.status === "needs_confirmation" && (
        <div className="m-4 rounded-md border border-mod bg-mod-soft p-4 text-sm">
          <h3 className="text-lg font-semibold text-mod">Confirm before I build this</h3>
          <ul className="mt-1 list-disc pl-5">{res.questions.map((q: string) => <li key={q}>{q}</li>)}</ul>
        </div>
      )}

      {res?.draft && (
        <p role="status" className="mx-4 mt-4 flex items-center gap-2 rounded-md bg-spot-soft px-3 py-2 text-sm text-spot">
          <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-spot" aria-hidden />
          Quick plan from the rules, already safety-checked. The composer is refining it; it will update here.
        </p>
      )}
      {res?.status === "ok" && <PlanCard res={res} rated={rated} rate={rate} />}
    </div>
  );
}

function PlanCard({ res, rated, rate }: { res: any; rated: string; rate: (r: "up" | "down") => void }) {
  const p = res.plan;
  const excluded = res.provenance.activities[1].generated_excluded as any[];
  const repairs = res.provenance.activities[3].repairs as string[];
  const blocks = ["warmup", "main", "accessory"];
  return (
    <div className="p-4">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-2xl font-semibold">{p.est_min} of {p.budget_min} min · {p.items.length} exercises</h3>
        <span className="text-sm text-iron">{res.draft ? "Draft" : `Version ${res.version}`} · built by {p.builder === "llm" ? "the composer model" : "the rule-based planner"}</span>
      </div>
      {p.summary && <p className="mb-3 text-sm text-iron">{p.summary}</p>}

      {blocks.map((b) => {
        const items = p.items.filter((i: any) => i.block === b);
        if (!items.length) return null;
        return (
          <section key={b} className="mb-4">
            <h4 className="display mb-1 text-lg font-semibold text-iron">{b === "warmup" ? "Warm-up" : b === "main" ? "Main work" : "Accessories"}</h4>
            <ol className="divide-y divide-rule rounded-md border border-rule">
              {items.map((i: any) => (
                <li key={i.exercise_id} className="grid grid-cols-[44px_minmax(0,1fr)] gap-x-3 gap-y-1 p-3 sm:grid-cols-[44px_minmax(0,1fr)_200px]">
                  <Glyph name={i.glyph} label={i.name} />
                  <div>
                    <p className="font-medium">{i.name}{i.each_side && <span className="text-iron"> · each side</span>}</p>
                    {i.cue && <p className="text-sm text-mod">Cue: {i.cue}</p>}
                    {i.why?.filter(Boolean).length > 0 && <p className="text-sm text-iron">{i.why.filter(Boolean).slice(0, 2).join("; ")}</p>}
                  </div>
                  <p className="display col-start-2 text-lg sm:col-start-3 sm:text-right">
                    {i.sets} × {i.reps ? `${i.reps} reps` : `${i.duration_s}s`}
                    <span className="block text-sm text-iron" style={{ fontFamily: "var(--font-body)" }}>
                      {i.rest_s ? `rest ${i.rest_s}s` : ""}{i.rpe_target ? ` · RPE ${i.rpe_target}` : ""}
                    </span>
                  </p>
                </li>
              ))}
            </ol>
          </section>
        );
      })}

      <details className="rounded-md border border-rule bg-chalk p-3" open>
        <summary className="cursor-pointer text-lg font-semibold">
          Why this plan: {excluded.length} left out, {res.provenance.summary.find((s: string) => s.includes("modification")) ?? "no modifications"}
        </summary>
        <ul className="mt-2 list-disc space-y-0.5 pl-5 text-sm">{res.provenance.summary.map((s: string) => <li key={s}>{s}</li>)}</ul>

        {res.graph && <><h5 className="mt-3 font-semibold">The graph paths behind this plan</h5><PathGraph graph={res.graph} /></>}

        <h5 className="mt-3 font-semibold">How your request was read</h5>
        <table className="mt-1 w-full text-left text-sm">
          <thead className="text-iron"><tr><th>Words</th><th>Concept</th><th>Role</th><th className="hidden sm:table-cell">Match</th></tr></thead>
          <tbody>{res.resolution.mentions.map((x: any, k: number) => (
            <tr key={k} className="border-t border-rule"><td>“{x.text}”{x.side ? ` (${x.side})` : ""}</td><td>{x.concept}</td><td>{x.role}</td>
              <td className="hidden sm:table-cell">{x.pass} · {x.extractor} · {x.confidence}</td></tr>
          ))}</tbody>
        </table>

        <h5 className="mt-3 font-semibold">Left out, and the rule that did it</h5>
        <ul className="mt-1 max-h-56 space-y-1 overflow-auto text-sm">
          {excluded.map((e) => (
            <li key={e.exercise}><span className="text-excl">{e.exercise}</span>: {e.reason.text}
              {e.reason.source && <span className="text-iron"> (source: {e.reason.source})</span>}</li>
          ))}
        </ul>

        {Object.keys(res.substitutions).length > 0 && (<>
          <h5 className="mt-3 font-semibold">Alternatives for exercises she's done recently</h5>
          <ul className="mt-1 text-sm">{Object.entries(res.substitutions).map(([k, v]: any) => (
            <li key={k}>{k}: {v.length ? v.map((s: any) => `${s.name} (${s.why})`).join("; ") : "no safe equivalent with this equipment"}</li>
          ))}</ul>
        </>)}

        {repairs.length > 0 && (<><h5 className="mt-3 font-semibold">Validator changes</h5>
          <ul className="list-disc pl-5 text-sm">{repairs.map((r) => <li key={r}>{r}</li>)}</ul></>)}

        <p className="mt-3 text-xs text-iron">
          Request {res.trace.request_id} · {res.trace.total_ms} ms · {res.trace.stages.map((s: any) => `${s.stage} ${s.ms}ms`).join(", ")}
          {res.trace.cost_usd ? ` · $${res.trace.cost_usd}` : ""} · <a className="underline" href={`/api/prov/${res.trace.request_id}`} target="_blank" rel="noreferrer">PROV-O record (Turtle)</a>.
          {" "}Clinical rules are unreviewed and need clinician sign-off.
        </p>
      </details>

      <div className="mt-3 flex items-center gap-2 text-sm">
        <span className="text-iron">Was this plan right for her?</span>
        <button onClick={() => rate("up")} disabled={!!rated || res.draft} aria-pressed={rated === "up"} className="rounded border border-rule px-2 py-1">👍</button>
        <button onClick={() => rate("down")} disabled={!!rated || res.draft} aria-pressed={rated === "down"} className="rounded border border-rule px-2 py-1">👎</button>
        {rated && <span className="text-ok">Feedback saved</span>}
      </div>
    </div>
  );
}
