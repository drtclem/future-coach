import { useEffect, useState } from "react";
import { api } from "./api";

// Plain-language summary of what intake extracted; unknown fields fall back to "key: value".
function readAs(x: Record<string, any>): string {
  return Object.entries(x).map(([k, v]) => {
    if (k === "sleep_hours") return `slept ${v} h`;
    if (k === "time_available_min") return `${v} min available`;
    if (k === "context") return String(v).replace("one-off cause mentioned: ", "one-off cause: ").replace(/'/g, "");
    if (k === "equipment_today") return `equipment today: ${(v as string[]).join(", ")}`;
    if (k === "pain") return `pain in ${v.area}${v.score != null ? ` (${v.score}/10)` : ""}`;
    return `${k.replace(/_/g, " ")}: ${typeof v === "object" ? JSON.stringify(v) : v}`;
  }).join(" · ");
}

export default function Inbox({ memberKey, firstName, onChange }: { memberKey: string; firstName?: string; onChange: () => void }) {
  const [text, setText] = useState("baby was up all night, I slept 4 hours. only have 20 min today");
  const [out, setOut] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  // The re-plan runs on the server after the reply is sent; poll until it lands.
  useEffect(() => {
    if (out?.replan?.status !== "pending") return;
    const t = setInterval(async () => {
      const r = await api(`/members/${memberKey}/replan`);
      if (r && r.status !== "pending") { setOut((o: any) => ({ ...o, replan: r })); onChange(); }
    }, 2000);
    return () => clearInterval(t);
  }, [out?.replan?.status, memberKey]);

  async function send() {
    setBusy(true);
    try { setOut(await api(`/members/${memberKey}/messages`, { text })); onChange(); }
    finally { setBusy(false); }
  }
  async function reset() { await api("/demo/reset", {}); setOut(null); onChange(); }

  return (
    <div className="rounded-lg border border-rule bg-card p-4">
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-xl font-semibold">Message from {firstName ?? "the member"}</h2>
        <button onClick={reset} className="text-sm text-iron underline">Reset demo data</button>
      </div>
      <p className="text-sm text-iron">Simulates the member app. New information re-plans today's session if one exists.</p>
      <form className="mt-2 flex flex-col gap-2 sm:flex-row" onSubmit={(e) => { e.preventDefault(); send(); }}>
        <label htmlFor="msg" className="sr-only">Member message</label>
        <input id="msg" value={text} onChange={(e) => setText(e.target.value)} className="min-w-0 flex-1 rounded-md border border-rule bg-chalk px-3 py-2 text-sm" />
        <button disabled={busy} className="rounded-md border border-spot px-3 py-2 text-sm text-spot disabled:opacity-60">Send as {firstName ?? "member"}</button>
      </form>
      {out && (
        <div className="mt-3 space-y-1 text-sm">
          <p><b>Reply sent to {firstName}:</b> “{out.reply_to_member}”</p>
          {Object.keys(out.extracted ?? {}).length > 0 && <p className="text-iron">Read as: {readAs(out.extracted)}</p>}
          {out.flags?.map((f: string) => <p key={f} className="rounded bg-mod-soft px-2 py-1 text-mod">{f}</p>)}
          {out.replan?.status === "pending" && <p role="status" className="text-iron">Updating today's plan…</p>}
          {out.replan?.version && (
            <p className="rounded bg-spot-soft px-2 py-1">Today's plan updated to version {out.replan.version} ({out.replan.reason}).
              {out.replan.removed.length > 0 && ` Removed: ${out.replan.removed.join(", ")}.`}
              {out.replan.added.length > 0 && ` Added: ${out.replan.added.join(", ")}.`}
              {` Time ${out.replan.est_min[0]} → ${out.replan.est_min[1]} min.`}</p>
          )}
          {out.replan === null && <p className="text-iron">No plan for today yet, so nothing to re-plan.</p>}
        </div>
      )}
    </div>
  );
}
