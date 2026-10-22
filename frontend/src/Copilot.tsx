import { useEffect, useRef, useState } from "react";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "./api";

const SUGGESTIONS = ["Give me the morning brief", "Congratulate her on yesterday's workout", "What changed since last week?",
  "How's adherence trending?", "Show her sleep this week", "Compare adherence over the last 4 weeks", "Show message pattern",
  "Is she a churn risk?"];

type Turn = { q: string; a?: any; error?: string };

export default function Copilot({ memberKey, firstName }: { memberKey: string; firstName?: string }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => setTurns([]), [memberKey]);
  useEffect(() => end.current?.scrollIntoView({ block: "nearest" }), [turns]);

  async function ask(question: string) {
    if (!question.trim()) return;
    setQ(""); setBusy(true);
    setTurns((t) => [...t, { q: question }]);
    try {
      const a = await api(`/members/${memberKey}/copilot`, { question });
      setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, a } : x)));
    } catch (e: any) {
      setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, error: e.message } : x)));
    } finally { setBusy(false); }
  }

  return (
    <div className="flex h-full max-h-[calc(100vh-110px)] flex-col rounded-lg border border-rule bg-card lg:sticky lg:top-4">
      <h2 className="border-b border-rule p-4 text-xl font-semibold">Ask about {firstName ?? "this member"}</h2>
      <div className="flex-1 space-y-4 overflow-auto p-4" aria-live="polite">
        {turns.length === 0 && (
          <div className="flex flex-wrap gap-1.5">
            {SUGGESTIONS.map((s) => <button key={s} onClick={() => ask(s)} className="rounded-full border border-rule px-2.5 py-1 text-xs text-iron hover:border-spot hover:text-spot">{s}</button>)}
          </div>
        )}
        {turns.map((t, i) => (
          <div key={i} className="space-y-2">
            <p className="ml-8 rounded-lg bg-spot-soft px-3 py-2 text-sm">{t.q}</p>
            {t.error && <p className="text-sm text-excl">Couldn't answer: {t.error}</p>}
            {!t.a && !t.error && <p className="text-sm text-iron">Looking it up…</p>}
            {t.a && <Answer a={t.a} />}
          </div>
        ))}
        <div ref={end} />
      </div>
      <form onSubmit={(e) => { e.preventDefault(); ask(q); }} className="flex gap-2 border-t border-rule p-3">
        <label htmlFor="ask" className="sr-only">Question</label>
        <input id="ask" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask a question or request a workout"
          className="min-w-0 flex-1 rounded-md border border-rule bg-chalk px-3 py-2 text-sm" />
        <button disabled={busy} className="rounded-md bg-spot px-3 py-2 text-sm text-white disabled:opacity-60">Ask</button>
      </form>
    </div>
  );
}

function Answer({ a }: { a: any }) {
  if (a.workout && !a.answer) {
    const w = a.workout;
    return <p className="text-sm">{w.status === "ok" ? `Built a ${w.plan.est_min}-minute plan with ${w.plan.items.length} exercises: `
      + w.plan.items.map((i: any) => i.name).join(", ") + "." : w.questions?.join(" ")}</p>;
  }
  const ev = Object.fromEntries((a.evidence ?? []).map((e: any) => [e.id, e]));
  return (
    <div className="space-y-2 text-sm">
      {a.answer.map((p: any, i: number) => (
        <p key={i}>{p.text}{" "}
          {p.evidence.map((id: string) => (
            <abbr key={id} title={`${ev[id]?.text ?? ""}\n${ev[id]?.node ?? ""}`} className="ml-0.5 cursor-help rounded bg-chalk px-1 text-xs text-spot no-underline">{id}</abbr>
          ))}
        </p>
      ))}
      {a.charts.map((c: any) => <Chart key={c.title} c={c} />)}
      <p className="text-xs text-iron">{a.builder === "llm" ? "Written by the analyst model" : "Rule-based answer"} · every claim cites its source; hover an id to see it.</p>
    </div>
  );
}

function Chart({ c }: { c: any }) {
  const data = c.x.map((x: string, i: number) => ({ x: x.slice(5), v: c.series[0].values[i] }));
  return (
    <figure className="rounded-md border border-rule p-2">
      <figcaption className="mb-1 font-medium">{c.title}</figcaption>
      <div className="h-40">
        <ResponsiveContainer>
          {c.type === "line" ? (
            <LineChart data={data}><CartesianGrid stroke="#e7ebee" vertical={false} /><XAxis dataKey="x" fontSize={11} /><YAxis fontSize={11} width={28} />
              <Tooltip />{c.goal && <ReferenceLine y={c.goal} stroke="#9a6400" strokeDasharray="4 3" label={{ value: `goal ${c.goal}${c.unit}`, fontSize: 10, fill: "#9a6400" }} />}
              <Line dataKey="v" stroke="#0e7470" strokeWidth={2} dot={{ r: 2 }} name={c.series[0].name} isAnimationActive={false} /></LineChart>
          ) : (
            <BarChart data={data}><CartesianGrid stroke="#e7ebee" vertical={false} /><XAxis dataKey="x" fontSize={11} /><YAxis fontSize={11} width={28} allowDecimals={false} />
              <Tooltip /><Bar dataKey="v" fill="#0e7470" name={c.series[0].name} radius={[3, 3, 0, 0]} isAnimationActive={false} /></BarChart>
          )}
        </ResponsiveContainer>
      </div>
      {c.note && <p className="text-xs text-iron">{c.note}</p>}
    </figure>
  );
}
