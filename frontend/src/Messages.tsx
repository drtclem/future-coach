import { useEffect, useRef, useState } from "react";
import { api } from "./api";

export function ChatHistory({ memberKey, firstName, rev }: { memberKey: string; firstName?: string; rev: number }) {
  const [msgs, setMsgs] = useState<any[] | null>(null);
  const [open, setOpen] = useState<any>(null);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { api(`/members/${memberKey}/messages`).then(setMsgs); }, [memberKey, rev]);
  useEffect(() => end.current?.scrollIntoView({ block: "nearest" }), [msgs]);
  if (!msgs) return null;
  let lastDay = "";
  return (
    <div className="rounded-lg border border-rule bg-card">
      <h2 className="border-b border-rule p-4 text-xl font-semibold">Chat with {firstName ?? "the member"}</h2>
      <ol className="max-h-[420px] space-y-2 overflow-auto p-4" aria-label="Message history, oldest first">
        {msgs.map((c, i) => {
          const day = c.ts.slice(0, 10);
          const showDay = day !== lastDay;
          lastDay = day;
          const coach = c.from === "coach";
          return (
            <li key={i}>
              {showDay && <p className="my-2 text-center text-xs text-iron">{new Date(day + "T12:00").toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })}</p>}
              <div className={`flex ${coach ? "justify-end" : "justify-start"}`}>
                <div className={`max-w-[80%] rounded-2xl px-3 py-2 text-sm ${coach ? "rounded-br-sm bg-spot text-white" : "rounded-bl-sm bg-chalk"}`}>
                  <p>{c.text}</p>
                  {c.attachments?.filter((a: any) => a.type === "image").map((a: any) => (
                    <button key={a.src} onClick={() => setOpen(a)} className="mt-2 block overflow-hidden rounded-lg border border-rule">
                      <img src={a.src} alt={a.caption} className="h-32 w-48 object-cover" />
                    </button>
                  ))}
                  <p className={`mt-0.5 text-[10px] ${coach ? "text-white/70" : "text-iron"}`}>
                    {coach ? "Coach" : firstName} · {c.ts.slice(11, 16)}{c.channel === "async" ? " · via app" : ""}
                  </p>
                </div>
              </div>
            </li>
          );
        })}
        <div ref={end} />
      </ol>
      {open && (
        <div role="dialog" aria-modal aria-label={open.caption} className="fixed inset-0 z-50 flex items-center justify-center bg-ink/70 p-6" onClick={() => setOpen(null)}>
          <figure className="max-w-2xl rounded-lg bg-card p-3" onClick={(e) => e.stopPropagation()}>
            <img src={open.src} alt={open.caption} className="w-full rounded" />
            <figcaption className="mt-2 flex items-center justify-between text-sm text-iron">{open.caption}
              <button autoFocus onClick={() => setOpen(null)} className="rounded border border-rule px-2 py-1">Close</button></figcaption>
          </figure>
        </div>
      )}
    </div>
  );
}

const SCALE = [1, 2, 3, 4, 5];

export function CheckinForm({ memberKey, firstName, injuries, onChange }:
  { memberKey: string; firstName?: string; injuries: any[]; onChange: () => void }) {
  const blank = { sleep_hours: "", energy: "", soreness: "", stress: "", pain_area: "", pain_score: "", time_available_min: "", note: "" };
  const [f, setF] = useState<Record<string, string>>(blank);
  const [out, setOut] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  const num = (v: string) => (v === "" ? null : Number(v));

  async function submit() {
    setBusy(true);
    try {
      setOut(await api(`/members/${memberKey}/checkins?source=coach-entered`, {
        sleep_hours: num(f.sleep_hours), energy: num(f.energy), soreness: num(f.soreness), stress: num(f.stress),
        time_available_min: num(f.time_available_min), note: f.note || null,
        pain: f.pain_area ? { area: f.pain_area, score: num(f.pain_score) } : null,
      }));
      setF(blank); onChange();
    } finally { setBusy(false); }
  }

  const field = "rounded-md border border-rule bg-chalk px-2 py-1.5 text-sm";
  return (
    <form className="rounded-lg border border-rule bg-card p-4" onSubmit={(e) => { e.preventDefault(); submit(); }}>
      <h2 className="text-xl font-semibold">Log a check-in for {firstName ?? "the member"}</h2>
      <p className="text-sm text-iron">Today's numbers can only make the plan more cautious, never less. Leave anything blank you don't know.</p>
      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <label className="flex flex-col gap-1 text-sm">Sleep last night (h)
          <input type="number" min={0} max={14} step={0.5} value={f.sleep_hours} onChange={set("sleep_hours")} className={field} /></label>
        <label className="flex flex-col gap-1 text-sm">Time today (min)
          <input type="number" min={5} max={120} step={5} value={f.time_available_min} onChange={set("time_available_min")} className={field} /></label>
        {(["energy", "soreness", "stress"] as const).map((k) => (
          <label key={k} className="flex flex-col gap-1 text-sm capitalize">{k} (1–5)
            <select value={f[k]} onChange={set(k)} className={field}><option value="">—</option>{SCALE.map((s) => <option key={s}>{s}</option>)}</select></label>
        ))}
        <label className="flex flex-col gap-1 text-sm">Pain area
          <select value={f.pain_area} onChange={set("pain_area")} className={field}>
            <option value="">none</option>
            {injuries.map((i) => <option key={i.id} value={i.label.split(" (")[0]}>{i.label.split(" (")[0]}</option>)}
            {["lower back", "shoulder", "knee", "hip", "ankle", "neck"].map((a) => <option key={a}>{a}</option>)}
          </select></label>
        {f.pain_area && <label className="flex flex-col gap-1 text-sm">Pain (0–10)
          <input type="number" min={0} max={10} value={f.pain_score} onChange={set("pain_score")} className={field} /></label>}
      </div>
      <label className="mt-3 flex flex-col gap-1 text-sm">Note (optional, read the same way as a message)
        <input value={f.note} onChange={set("note")} placeholder="e.g. baby up all night" className={field} /></label>
      <button disabled={busy} className="mt-3 rounded-md bg-spot px-4 py-2 text-sm font-medium text-white disabled:opacity-60">Save check-in</button>
      {out && (
        <div role="status" className="mt-3 space-y-1 text-sm">
          <p>Saved. Readiness is now <b>{out.readiness.level}</b> (RPE cap {out.readiness.rpe_cap}).</p>
          {out.flags.map((x: string) => <p key={x} className="rounded bg-mod-soft px-2 py-1 text-mod">{x}</p>)}
          {out.replan?.status === "pending" && <p className="text-iron">Today's plan is being updated in the background.</p>}
        </div>
      )}
    </form>
  );
}
