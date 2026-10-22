# Future Coach

A coach dashboard that generates safe, personalized workouts and answers questions about a member. Recommendations come from a knowledge graph. Every safety decision is a deterministic graph traversal, never a prompt instruction: a language model can propose, but only the graph can allow.

Design decisions, with the options considered for each: [`docs/DECISIONS.md`](docs/DECISIONS.md) (D1–D19).

Architecture, with diagrams: [`docs/architecture/ARCHITECTURE.md`](docs/architecture/ARCHITECTURE.md).

## Quick start

```bash
make run     # Python >= 3.12 + Node >= 20: installs, builds the dashboard, serves http://localhost:8000
make test    # LLM-free suite (no API key needed)
make eval    # golden set + gate (real model calls if keys are in .env, else offline)
make dev     # API with reload; run `cd frontend && npm run dev` for the dashboard with hot reload
```

API keys are optional. Copy `.env.example` to `.env` to turn on LLM features and Langfuse tracing. Without keys the app runs fully offline: rules-only extraction, the deterministic plan builder and a templated copilot writer. Every safety guarantee holds in both modes.

**Live demo:** https://198-199-77-33.sslip.io (behind one coach login; credentials shared with reviewers on request). To see a re-plan: click **Reset demo data**, build a session for Jordan, then send a message as her ("baby was up all night, I slept 4 hours. only have 20 min today"). The reply comes back at once, and the plan diff appears a few seconds later.

## What the coach gets

- **Workout Generator.** The coach types a request in plain words: "Lower body, avoid aggravating her knee, 30 min" or "No barbell today, only dumbbells and a kettlebell". The plan comes back with sets, reps, rest and RPE. Each exercise shows why it was picked, and each excluded exercise shows the rule that excluded it. If the request mentions a safety concern the system can't place ("something's off with her hammy"), it asks which body area before building anything.
- **Copilot.** Questions about the member ("Congratulate Jordan on yesterday's workout", "Is she a churn risk?", "Any lab concerns?") are answered from tools that return evidence with IDs. Every paragraph cites its evidence. The member's own words are quoted, never paraphrased. Labs are context for the care team, never advice.
- **Member inbox.** The member can check in on the day ("baby was up all night, I slept 4 hours") or message hours before a session. The message is parsed into readiness signals. If today's plan exists, it is re-planned, and the diff (removed, added, time change) is shown to the coach. The **Messages & check-ins** tab shows the full chat history (including image attachments) and a structured check-in form.
- **The graph, visible.** Every plan carries the graph paths behind it, drawn left to right (exercise → load on a structure → part-of → condition → rule) with tabs for injury rules, why each exercise was picked, exercise family and equipment. The **Member graph** tab shows what the system knows about the member (KG2) and the domain concepts it links to (KG1), read live with SPARQL. Every plan also has a PROV-O record, linked from the plan card.
- **At a glance.** Each workout item has a pictogram chosen deterministically from its movement pattern (`/#glyphs` shows the library). The member card shows a readiness meter, 14 nights of sleep against the goal, and adherence for completed weeks.

## Architecture

```
coach request ──► Router (rules + intent from the extraction call)
                     │ compose │ lookup │ analyze │ analyze+compose
                     ▼
   Resolver: rules extractor ‖ LLM extractor (timeout) ──► union (LLM can only add caution)
                     ▼
   Constraints: member injuries (KG2) + care-team notes + coach request + readiness
                     ▼
   SafetyFilter (graph traversal, deterministic) ──► safe set + reasons for every exclusion
                     ▼
   Scorer (targets, preferences, recency, journey stage)
                     ▼
   Composer: LLM picks from an enum of safe IDs  │  deterministic builder (fallback / offline)
                     ▼
   Validator (always runs): hallucination, safe substitution, duplicates, RPE cap, time window, fill
                     ▼
   Plan + provenance (every activity, rule and source)
```

**Knowledge graph.** Embedded Oxigraph (RDF + SPARQL), two named graphs:

- **KG1, domain:** anatomy with a two-way `part-of` hierarchy and SNOMED CT codes (codes only, see `NOTICE`); equipment families, capabilities and near-synonyms; movement patterns with load-type implications; the exercise catalog; clinical conditions with contraindication rules. Rules are data with a source, confidence and `review_status: unreviewed`.
- **KG2, member:** injuries as instances of a condition, care-team notes parsed into member rules, check-ins, messages and plan versions.

Exercises don't just "load the knee". Each one has n-ary **stress** nodes: exercise → (structure, load type, how it was derived). Knee load types are `impact`, `loaded_deep_flexion`, `loaded_shallow_flexion`, `open_chain_terminal`, `open_chain_midrange` and `contact_only`, with matching sets for the lumbar spine and shoulder. This is what lets the graph allow a wall sit for a patellofemoral knee while excluding jumping lunges, and allow kneeling exercises at all. Published guidelines recommend loading an injured knee progressively rather than avoiding it (see D2 and C13 in the decisions log).

### Graph schema

Three named graphs in one store. Counts are from the running app with the provided and synthetic data.

| Node type | Graph | Count | What it is | Aligned to |
|---|---|---|---|---|
| `Exercise` | KG1 | 70 | 50 catalog + 20 synthetic exercises | NCIT Exercise (close) |
| `MovementPattern` | KG1 | 38 | The catalog's 36 patterns + hinge and box/partial squat | EXMO/NCIT exercise types (exact, close or broad) |
| `Equipment`, `EquipmentFamily`, `Ambient` | KG1 | 35 + 1 + 2 | Catalog equipment, the barbell family, and always-available floor and wall | EXMO equipment (16 mapped) |
| `Muscle` | KG1 | 19 | The catalog's muscle groups, with coach slang as SKOS labels | none (our labels) |
| `Structure` | KG1 | 20 | Joints and sub-structures in a part-of hierarchy (knee → patellofemoral joint → patella) | SNOMED CT codes only |
| `BodyRegion` | KG1 | 8 | Request vocabulary ("lower body", "upper body") → the patterns it includes | none |
| `Condition` | KG1 | 4 | PFP, low back pain, rotator cuff tendinopathy, unspecified complaint | SNOMED CT codes; EXMO rotator cuff injury (broad) |
| `Rule` | KG1 | 21 | One contraindication rule: condition × load type × stage → tier, with cue, source, confidence and review status | none (our schema) |
| `ExerciseFamily` | KG1 | 1 | The deadlift family | none |
| `Member`, `Injury`, `Goal`, `WorkoutSession`, `Message` | KG2 | 3, 3, 6, 98, 24 | The member's world; an `Injury` is an instance of a `Condition` | none |
| `Plan`, `ExcludedExercise`, `prov:Activity`, `prov:Entity` | provenance | per plan | Why each plan looks the way it does | W3C PROV-O |

| Edge | From → to | Meaning |
|---|---|---|
| `stresses` (n-ary: `structure`, `loadType`, `derivation`) | Exercise → Structure | Which structure an exercise loads, how, and where that came from (usually its pattern). The spec's `stresses`, made specific enough to allow a box squat and exclude a jump |
| `partOf` | Structure → Structure | Anatomy hierarchy, walked both ways (`partOf*` / `^partOf*`) |
| `condition`, `loadType`, `stage`, `tier` | Rule → Condition, load type | The spec's `contraindicated-for`, as data: which load is excluded, down-ranked, allowed or recommended at which stage |
| `affects` | Condition → Structure | Where a condition sits in the anatomy |
| `targets` | Exercise → Muscle | The spec's `targets` |
| `requires` (n-ary: `equipment`, `quantity`) | Exercise → Equipment | The spec's `requires`, with quantity (all must be satisfied) |
| `provides`, `broader`, `closeMatch` | Equipment → Equipment | A bench works as a box; EZ bar is a barbell; miniband ≈ loop band (flagged in the trace) |
| `hasPattern`, `implies` | Exercise → Pattern → load | Pattern membership, and which load a pattern puts on which structure |
| `variantOf` | Exercise → ExerciseFamily | "No deadlift variations" without string matching |
| `pairedWith` | Exercise → Exercise | Left/right pair of a unilateral exercise |
| `instanceOf`, `at`, `laterality`, `memberRuleLoad` | Injury → Condition, Structure, side, load type | A member's injury, with care-team rules parsed from its note |
| `hasInjury`, `hasGoal`, `hasEquipment`, `hasWorkout`, `hasMessage` | Member → … | KG2; `hasEquipment` points at KG1 equipment nodes |
| `skos:prefLabel` / `altLabel` / `hiddenLabel` | any → text | What the resolver matches against |
| `skos:exactMatch` / `closeMatch` / `broadMatch` | our concept → EXMO, NCIT, SNOMED | Ontology alignment (`kg/ontology_alignment.ttl`, `kg/anatomy.ttl`, `kg/conditions.ttl`) |
| `prov:used`, `wasInformedBy`, `wasGeneratedBy`, `wasDerivedFrom`, `specializationOf`, `hadMember` | provenance | Per plan: activities, items, and each exclusion derived from its rule |

The edges the spec lists that no ontology provides (`stresses`, `contraindicated-for`) are our own schema; EXMO has only generic part-of and has-characteristic relations.

### The three required scenarios

| Request | How the graph handles it |
|---|---|
| Lower body that avoids aggravating a knee injury | The member's injury is an instance of a condition. Its rules exclude the load types that aggravate it (impact, loaded deep flexion), down-rank others with a cue, and leave the rest allowed. An ad-hoc complaint with no diagnosis ("his knee is bothering him") fails closed to the conservative rule set. |
| Full body, no deadlift variations | "Deadlift" resolves to a family node. Exclusion follows `variantOf`, so RDLs and trap-bar deadlifts go, while hinge-pattern work that isn't a deadlift (hip thrusts) stays. |
| Only dumbbells and a kettlebell | An "only" statement replaces the profile equipment for this session. Every exercise's required equipment, including quantity, must be satisfiable. Ambient items (floor, wall, mat) are always available. |

### Resolving free text

Each mention goes through three passes against the SKOS labels in the graph: **exact** (whole words, longest phrase first), **fuzzy** (rapidfuzz ≥ 88, restricted to the concept types the mention's role allows) and **embedding** (a local `bge-small` model, no key). The embedding pass is deliberately narrow:
- it only considers muscle and structure concepts, the gap it fills being body-part slang ("tummy" → core, "booty" → glutes);
- a match needs similarity ≥ 0.78 and a 0.03 margin over the next different concept, so ambiguous words ("spine") stay unresolved;
- it **never resolves a safety concern**: in a sentence with a pain or injury word it only suggests ("Did you mean the hamstrings?") and the plan still waits for the coach.

Thresholds were calibrated on slang versus filler words (filler tops out at 0.77 against body parts). The trace records which pass resolved each word.

### Fail-closed rules

- A safety cue ("pain", "sore", "tweaked") in a sentence with no resolved body area blocks the plan and asks the coach.
- A body area the LLM flags as a constraint that the graph can't resolve blocks the plan.
- A muscle named as a concern ("her hammy") asks which joint or area to protect.
- Goals fail open: an unresolved target just drops out, with a note.

### Example inputs and plans

[`docs/examples.md`](docs/examples.md) has four worked examples, each with the request, how it was resolved onto graph concepts, the plan, and the filtering trace (every exclusion with its rule, source and graph path):

1. **Injury:** Jordan, "Lower-body exercises that avoid aggravating a knee injury". Eight exercises are excluded by her care-team note through `knee → part-of → patellofemoral joint → PFP`. Step-ups and glute bridges stay, because guidelines say to load a PFP knee rather than avoid it.
2. **Limited equipment:** Priya, "No barbell today, only dumbbells and a kettlebell. Upper body". The coach's statement replaces her profile equipment for this plan. Her shoulder history keeps the overhead press at its prescribed dose with a progression cue, and the time-window fill never adds volume to injury-modified work.
3. **Exercise-family exclusion:** "Full body, no deadlift variations, 40 min". Five deadlift variants are excluded through `variant-of → deadlift`, while kettlebell swings stay, because they're hinge work but not a deadlift.
4. **Fail closed:** "Something's off with her hammy, sore since Saturday". There is no plan; the system asks which body area is affected.

`make examples` regenerates the file offline, so the output is reproducible.

## Personalization over the member's journey

Signals are computed deterministically in `app/member/signals.py`, one job per timescale:

- **Readiness (day-of):** sleep, soreness, stress and energy from check-ins and messages. Readiness can only lower intensity: RPE caps of 8 / 7 / 6, volume factors of 1 / 0.85 / 0.6.
- **Journey stage:** onboarding, building, established, at-risk, rehab. The stage changes exercise selection, progression and how much novelty the plan includes.
- **Adherence and churn:** churn is computed from completed weeks only. The brief's 50% for a two-day-old week is explained, not counted.
- **History:** recently done exercises are down-ranked for variety; dislikes are respected; time-window preferences are balanced against how long sessions actually run.

## Agents and models

A deterministic spine (resolver, safety filter, scorer, validator, provenance) is shared by three agents: Composer, Lookup and Analyst. A router picks between them using rules plus an intent field from the extraction call the resolver already makes, so routing adds no extra model call. A misroute can produce a worse answer but never an unsafe one, because every route that outputs exercises passes the same gate.

LiteLLM (in-process) gives each tier a cross-provider fallback:

| Tier | Primary | Fallback | Used for |
|---|---|---|---|
| small | claude-haiku-5-5 | gpt-5-mini | extraction, routing, Composer |
| mid | claude-sonnet-5-5 | gpt-5.4 | Analyst |
| large | claude-opus-5-5 | gpt-5.4 | available, not used by default |

The deterministic builder and writer are the floor under every model call.

## Latency

Measured on the golden set (CI runner, real models):

| Path | Typical | Notes |
|---|---|---|
| Offline / blocked request | 15–45 ms (blocks ~1.5–2 s with the LLM extractor) | Graph traversal is not the bottleneck |
| Workout, draft plan (streamed first) | ~1.5–2 s | Same path as a blocked request, plus a <50 ms build; already validated |
| Workout, LLM composer (replaces the draft) | 8–20 s | Arrives while the coach is already reading the draft |
| Copilot, analyst (mid tier) | 4–15 s | Lookup questions skip the LLM |

**How the dashboard stays under ~5 s:** the LLM composer alone takes 8–20 s, so plans are streamed (`POST /api/members/{key}/generate/stream`, server-sent events). As soon as the safe candidates are scored, the coach gets a **draft** from the deterministic builder, through the same validator, typically within 2 s (the LLM extraction call is the wait). The composer's plan replaces it when it lands, and only that final plan is stored as a version. Both pass the same safety gate, so the draft is never less safe; it is only less polished. Member messages and check-ins already avoid the wait: the member gets the reply at once, and the re-plan runs in the background. Tiers and timeouts are configurable (`FC_COMPOSE_TIER`, `FC_COMPOSE_TIMEOUT`, `FC_ANSWER_TIER`, `FC_EXTRACT_TIMEOUT`).

## Observability and evals

Modeled on the clinical-copilot (OpenEMR) project:

- **Traces.** Every request gets a trace: route and confidence, resolver mentions by extractor, constraints, exclusions with reasons, model, tokens, cost and latency per step. Traces go to Langfuse when keys are set, otherwise to structured JSON logs. Coach feedback (`/api/feedback`) is attached to the trace as a score. Member and coach free text is never logged; the eval gate checks this.
- **Golden set** (`backend/evals/cases.py`, 23 cases): the three required scenarios across members, prompt-injection attempts through member messages, coach requests and the copilot, the traps from the spec review (`back squat` isn't a back injury, `my pecs` is a target, an unresolvable hammy must block), readiness and message cases, and copilot grounding cases. Safety is re-derived from the graph independently; the pipeline's own claims are not trusted.
- **Gate** (`backend/evals/gate.py`): every case must pass, and every metric must meet its floor and not regress more than 5% (relative) against `baseline_results.json`, which only a human commits.

| Metric | Floor |
|---|---|
| schema_valid, safety_respected, citation_present, grounded, fail_closed, plan_fill, no_member_text_in_logs | 100% |
| llm_path (the model path actually worked instead of silently falling back) | 80% |

`plan_fill` is an anti-gaming guard: an empty plan is trivially safe.

Running the gate against real models found more than a dozen bugs the offline suite couldn't, from a model rejecting `temperature=0` to an Analyst answer that mentioned supplements and a copilot that silently fell back to templates on a stray comma. Each is now a test, listed in the commit history from MR !7 on.

## Evaluating it in production

The eval gate protects each release. In production, these are the questions to answer every week.

**Is it safe?**
- **Safety-override rate:** how often the validator replaces or drops a model-proposed exercise. A rising rate means the composer is drifting, even though nothing unsafe reaches a coach. Alert on spikes.
- **Fail-closed rate and resolution:** how often a request is blocked, and what the coach answered. Recurring answers ("hammy" means hamstring) become new graph labels, reviewed before merge.
- **Sampled clinical review:** a clinician reviews a weekly sample of plans for members with active injuries, with the trace attached. Every rule ships `unreviewed`; this review is how rules get signed off.
- **Independent re-check:** run the golden set's graph-based safety check over every production plan, offline and nightly. Any mismatch is a P0.

**Is it useful?**
- **Coach edit rate:** the share of plans the coach changes before sending, and which exercises get swapped out. This is the best quality signal.
- **Thumbs up/down** on plans and copilot answers (already attached to traces), broken down by route, member stage and model.
- **Re-plan acceptance:** how often a coach keeps the re-planned version after a member message.
- **Member outcomes:** session completion and reported pain after sessions built by the system vs. coach-built ones. Pain reported after a plan is the signal that matters most.

**Is it working?**
- **Latency per stage and fallback rate** per provider and tier (from traces). A climbing fallback rate means a provider problem or a prompt regression.
- **Cost per plan and per copilot answer**, with spend caps on the provider keys.
- **Grounding rejections:** how often copilot answers fail the grounding check, and why.

**Known failure modes to watch:**
- **Misresolution:** a word maps to the wrong concept, as "back" in "back squat" would without the rule that already handles it. Watch fuzzy matches with low confidence.
- **Stale or wrong member data:** an injury healed but not updated, or a wrong side recorded. The plan is only as safe as the record, so show the injury's last-updated date to the coach.
- **Rule gaps:** a condition with no rules falls back to the conservative default. Track how often that happens per condition.
- **Provider outage:** fallback goes to the other provider, then to the deterministic builder, so a plan is always available.

## Data

- `data/exercises.json` and `data/member-context.json` are untouched.
- `data/exercises_synthetic.json` adds 20 exercises, each with a reason (for example, the catalog had no deadlift at all).
- `data/members/` holds three synthetic members generated by `scripts/generate_synthetic.py` (seeded). Jordan extends the provided member and preserves every provided value; Sam (full gym, no injury record) and Priya (home gym, shoulder history) exist to test the same scenarios on different profiles.
- Ingestion normalizes the data-quality issues it finds and logs every fix (`GET /api/kg/normalization`).

## Tech choices

| Choice | Why |
|---|---|
| pyoxigraph (embedded RDF/SPARQL) | Graph-native, standards-based, no server; `make run` stays one command |
| SKOS labels + rapidfuzz | Deterministic, explainable resolution onto canonical concepts |
| EXMO where it fits, SNOMED CT codes, own schema for gaps | 47 EXMO/NCIT mappings, each checked against the current EXMO release. COPPER was evaluated but not mapped: its own IRIs don't resolve and it is non-commercial |
| fastembed (`bge-small-en-v1.5`, ONNX) | The resolver's embedding pass runs locally with no key and no PyTorch; warmed at startup |
| FastAPI + pydantic | Typed contracts at the boundary |
| LiteLLM as a library | Provider fallback and cost tracking without running a proxy |
| Langfuse | Same tracing setup as the clinical-copilot project |
| React + Vite + Tailwind + Recharts | Fast to build; the dashboard is served by the API |
| Append-only event log (`var/events.jsonl`) | Check-ins, messages and plan versions survive restarts and replay into KG2 |

## Tests: what they cover and why

128 LLM-free tests run on every commit (`make test`), and the golden set runs against real models on every merge request. The tests follow the failure that would hurt most, not the line count:

1. **Safety filter** (`test_safety.py`, the largest file). A wrong answer here hurts a member. Covers part-of in both directions, laterality, the deadlift family, equipment quantity and capabilities, stage tiers, strictest-tier-wins and care-team notes.
2. **Resolver** (`test_resolver.py` + a 30-phrase golden file). This is where free text meets safety. Covers the known traps ("back squat" is not the back, "kneeling" is not the knee, "my pecs" is a target), polarity, fail-closed on unresolved concerns, and the embedding pass's three guarantees (resolves slang targets, never resolves a safety concern, ignores filler and ambiguous words).
3. **Validator and composer** (`test_generate.py`). The model's output is the untrusted input: hallucinated or excluded IDs, a malicious plan with every field wrong, dose clamps and time fit.
4. **Copilot grounding** (`test_copilot.py`). Uncited claims, quotes that aren't verbatim, clinical advice, and planner arguments a tool doesn't take (a bug the real-model golden set found).
5. **Graph and API** (`test_graph.py`, `test_api.py`). Ingestion counts, ontology alignments attach to real nodes and never widen equipment, the PROV-O record is valid and survives replay.

The golden set (`backend/evals/`) re-derives safety from the graph independently instead of trusting the pipeline's own trace.

## What I cut, and why

- **Real auth and multi-coach tenancy.** The dashboard has a mock coach sign-in (the spec allows it) and the server sits behind one Caddy login. Real accounts are required before the app is public.
- **Token-by-token streaming of the composer's output.** The dashboard streams a validated draft and then the final plan; streaming partial model output would show text the validator hasn't checked yet.
- **A trained router (LAYA).** Zero-shot quality is weak and it needs training data. Every routing decision is logged so that dataset builds itself.
- **Clinician review of rules.** Every rule ships as `unreviewed` with its source and confidence. The workflow to sign them off is designed but not built.
- **Real member-app integration.** The inbox panel simulates the member side.
- **COPPER mappings.** Evaluated; its IRIs don't resolve and its license is non-commercial, so behavior-change concepts stay in our own schema.
- **A force-directed graph explorer.** The graph views use a deterministic column layout instead: the same input always draws the same picture, which matters when a coach compares two plans.
- **Production docs from the plan** (`KEY_METRICS.md`, `COST_ANALYSIS.md`, `THREAT_MODEL.md`, a Locust load test and a resolver pass-frequency report). The data for each is in the traces; the write-ups are not.

## ⚠️ Before any commercial use

- **COPPER** is CC BY-NC 4.0. It is not mapped today; license it before adding any mapping.
- **SNOMED CT** needs licensing confirmed (Affiliate / UMLS).
- **Clinical rules** need a clinician owner.

Details are in `docs/DECISIONS.md` and `NOTICE`.

## How AI was used

The design was worked out one decision at a time in conversation with Claude, with pros, cons and options for each (`docs/DECISIONS.md`). A research subagent gathered the clinical evidence behind the condition rules. Claude wrote the code in vertical slices, each shipped through a merge request that had to pass CI. A human set the direction, made every product call and owns the eval baseline.

## Development workflow

| Piece | When it runs | What it does | If it fails |
|---|---|---|---|
| pre-commit | `git commit` | ruff lint/format, whitespace, YAML/JSON checks, gitleaks secret scan | Fix the error shown, `git add`, commit again |
| commit-msg | `git commit` | Requires Conventional Commits (`feat: ...`, `fix: ...`, `chore: ...`) | Rewrite the message |
| pre-push | `git push` | LLM-free test suite | Fix before pushing; CI would fail anyway |
| CI `lint` | Every MR and push to `main` | All pre-commit hooks on all files | Open the failing job in the MR's Pipelines tab |
| CI `eval_unit_tests` | Every MR and `main` | Safety, graph, resolver, plan, copilot and API tests | Same |
| CI `frontend_build` | Every MR and `main` | Builds the dashboard | Same |
| CI `eval_golden_set` | Ready MRs and `main` | Golden set against real models, then the gate | Read the results table in the job log |

`main` is protected: no direct pushes, and an MR merges only when its pipeline passes. Escape hatch: `git commit --no-verify` skips local hooks for one commit; CI still checks.

## Deployment

The app runs on a DigitalOcean droplet (Ubuntu 24.04) behind Caddy, with automatic HTTPS at `https://198-199-77-33.sslip.io` and one coach login.

- **One-time setup:** `ssh root@<IP> 'bash -s' -- "$(cat ~/.ssh/future_coach_deploy.pub)" < scripts/bootstrap.sh`. It creates a `deploy` user, turns on the firewall, installs the systemd service and Caddy, and prints the dashboard login once.
- **Every merge to `main`:** the `deploy` job builds the dashboard, rsyncs it to the droplet as `deploy`, restarts the service and checks `/api/health`. The job is skipped until the `SSH_DEPLOY_KEY` CI variable exists.
- **Secrets:** provider and Langfuse keys live only in masked GitLab CI variables. Each deploy writes them to an owner-only file on the server (`/var/lib/future_coach/ci.env`); they are never in the repo or job logs. Member events persist in `/var/lib/future_coach/events.jsonl`.
