import { useEffect, useState } from "react";
import { api } from "./api";
import Generator from "./Generator";
import Copilot from "./Copilot";
import Inbox from "./Inbox";
import { MemberCard, MemberGraph } from "./Member";
import { ChatHistory, CheckinForm } from "./Messages";

type MemberSummary = { key: string; name: string; pronouns: string; as_of: string };
type Tab = "plan" | "graph" | "messages" | "copilot";
const TABS: { id: Tab; label: string; wideToo: boolean }[] = [
  { id: "plan", label: "Build a session", wideToo: true },
  { id: "graph", label: "Member graph", wideToo: true },
  { id: "messages", label: "Messages & check-ins", wideToo: true },
  { id: "copilot", label: "Copilot", wideToo: false }, // beside the main column on wide screens
];

// Mock auth (the spec allows it): the name lives in sessionStorage only. Real auth is Caddy's login on the server.
const read = () => { try { return sessionStorage.getItem("coach") ?? ""; } catch { return ""; } };
const write = (v: string) => { try { v ? sessionStorage.setItem("coach", v) : sessionStorage.removeItem("coach"); } catch { /* storage blocked */ } };

export default function App() {
  const [coach, setCoach] = useState(read);
  if (!coach) return <SignIn onSignIn={(n) => { write(n); setCoach(n); }} />;
  return <Dashboard coach={coach} onSignOut={() => { write(""); setCoach(""); }} />;
}

function SignIn({ onSignIn }: { onSignIn: (name: string) => void }) {
  const [name, setName] = useState("Coach Alex");
  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <form onSubmit={(e) => { e.preventDefault(); if (name.trim()) onSignIn(name.trim()); }} className="w-full max-w-sm space-y-4 rounded-lg border border-rule bg-card p-6">
        <div>
          <h1 className="text-3xl font-semibold">Future Coach</h1>
          <p className="text-sm text-iron">Demo sign-in. Every member here is synthetic.</p>
        </div>
        <label className="flex flex-col gap-1 text-sm">Coach name
          <input autoFocus value={name} onChange={(e) => setName(e.target.value)} className="rounded-md border border-rule bg-chalk px-3 py-2 text-base" /></label>
        <label className="flex flex-col gap-1 text-sm">Password
          <input type="password" placeholder="any value works in the demo" className="rounded-md border border-rule bg-chalk px-3 py-2 text-base" /></label>
        <button className="w-full rounded-md bg-spot px-4 py-2 font-medium text-white">Sign in</button>
      </form>
    </main>
  );
}

function Dashboard({ coach, onSignOut }: { coach: string; onSignOut: () => void }) {
  const [members, setMembers] = useState<MemberSummary[]>([]);
  const [key, setKey] = useState("jordan");
  const [m, setM] = useState<any>(null);
  const [tab, setTab] = useState<Tab>("plan");
  const [rev, setRev] = useState(0); // bump to refresh member data after check-ins and messages
  const refresh = () => setRev((r) => r + 1);
  const first = m?.profile?.name?.split(" ")[0];

  useEffect(() => { api<MemberSummary[]>("/members").then(setMembers); }, []);
  useEffect(() => { api(`/members/${key}`).then(setM); }, [key, rev]);
  useEffect(() => setM(null), [key]);

  // The copilot tab only exists on narrow screens; on wide screens fall back to the session tab.
  const main: Tab = tab === "copilot" ? "plan" : tab;
  return (
    <div className="min-h-screen">
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-rule bg-card px-4 py-3 md:px-6">
        <h1 className="text-2xl font-semibold">Future Coach</h1>
        <p className="text-sm text-iron">
          Synthetic data · as of {members.find((x) => x.key === key)?.as_of ?? "…"} · {coach}{" "}
          <button onClick={onSignOut} className="underline">Sign out</button>
        </p>
      </header>

      <div className="mx-auto grid max-w-[1560px] gap-4 p-4 md:p-6 lg:grid-cols-[300px_minmax(0,1fr)_420px]">
        <aside className="space-y-4" aria-label="Member">
          <label className="block">
            <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-iron">Trainee</span>
            <select value={key} onChange={(e) => setKey(e.target.value)}
              className="w-full rounded-md border border-rule bg-card px-3 py-2 text-sm font-medium text-ink focus:border-spot">
              {members.map((x) => <option key={x.key} value={x.key}>{x.name} ({x.pronouns})</option>)}
            </select>
          </label>
          {m ? <MemberCard m={m} /> : <p className="text-sm text-iron">Loading member…</p>}
        </aside>

        <main className="min-w-0">
          <div className="mb-3 flex flex-wrap gap-1" role="tablist" aria-label="Work area">
            {TABS.map((t) => (
              <button key={t.id} role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)}
                className={`${t.wideToo ? "" : "lg:hidden"} rounded-md px-3 py-1.5 text-sm ${tab === t.id ? "bg-spot text-white" : "border border-rule bg-card"}`}>
                {t.label}
              </button>
            ))}
          </div>
          <div className={tab === "copilot" ? "hidden lg:block" : ""}>
            <div hidden={main !== "plan"}><Generator memberKey={key} member={m} /></div>
            {main === "graph" && <MemberGraph memberKey={key} rev={rev} />}
            {main === "messages" && (
              <div className="space-y-4">
                <ChatHistory memberKey={key} firstName={first} rev={rev} />
                <Inbox memberKey={key} firstName={first} onChange={refresh} />
                <CheckinForm memberKey={key} firstName={first} injuries={m?.injuries ?? []} onChange={refresh} />
              </div>
            )}
          </div>
        </main>

        <section className={tab === "copilot" ? "" : "hidden lg:block"} aria-label="Copilot">
          <Copilot memberKey={key} firstName={first} />
        </section>
      </div>
    </div>
  );
}
