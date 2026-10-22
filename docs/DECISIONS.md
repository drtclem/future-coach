# Decision Log

This is a running record of design decisions. Each one cross-references SPEC_REVIEW.md (§) where relevant. The log feeds two README sections: trade-offs, and "What I cut and why". Clinical sources are in `research/clinical_rules_research.md`.

**Guiding principle (set 2026-10-14):** when the data or spec is ambiguous, choose what best serves the coach and the member. Each decision below starts with *what the user experiences*, then gives the implementation.

**Status:** ✅ decided · ⏳ pending

## Data facts (verified against data/exercises.json)

- The spec's counts match the files exactly: 50 exercises, 19 muscle groups, 9 joints, 36 movement patterns, 32 equipment types. (§3.1)
- `priority_tier` is 2 for all 50 exercises, so it carries no ranking value. (§3.2)
- `is_bilateral: true` means the exercise is one side of a mirrored left/right pair, so it is **unilateral**. It always appears together with a `side` and a `bilateral_pair_id` (18 exercises). Alternating two-limb exercises have `is_bilateral: false`.
- All 18 unilateral exercises are left-side variants. None of their `bilateral_pair_id`s resolve to an exercise in the catalog.
- Data-quality issues:
  - Empty `joints_loaded`: Alternating DB Decline Bench Press, and Lacrosse Ball Upper Back against Wall.
  - A duplicated joint: Alternating Low Plank to Low Side Plank.
- 21 exercises list "knee". Some of these only involve kneeling contact (Cow Pose, Bird Dog, World's Greatest Stretch).
- There is no deadlift exercise and no hinge movement pattern. The only deadlift anywhere is the KB RDL in the member's history.
- The member profile has `sex: female` and no pronoun field. (§3.3)

## Contradictions found (and how the product handles them)

| # | Contradiction | Resolution |
|---|---|---|
| C1 | SPEC_REVIEW §1.5 read `is_bilateral` as "uses both limbs". In the data it means the opposite. | Fixed in SPEC_REVIEW. Ingestion renames the field to `unilateral`. Safety is unaffected because the rule is whole-joint. |
| C2 | Adherence weeks start on **Tuesday**. The brief is dated Thu 06-04, so the 50% for the week of 06-02 covers a week that is only 2 days old. | See D5.3. |
| C3 | The adherence percentages can't be reproduced from `workout_history` (week of 05-26: about 67% from logged sessions vs. 75% reported). | Treat the adherence series as the source of truth and the history as a sample. The synthetic expansion must reconcile the two. |
| C4 | `dislikes: ["Deadlift"]`, yet she completed a KB RDL on 05-27. | See D5.4. |
| C5 | Her profile equipment includes a bench, a loop band and a mat. Her chat on 05-22 says "only DBs and a kettlebell". | See D4. |
| C6 | The brief says "first pain-free squat work". She said the knee "felt okay", and she had already done Step-Up and Wall Sit on 05-27. | See D5.5. |
| C7 | She wrote "Skipped Thursday", but the missed session is dated Fri 05-29. | Trust the dates. Minor; noted. |
| C8 | She prefers 50 min sessions, but her recent sessions ran 26–31 min. | See D5.6. |
| C9 | The 7 sleep values have no dates, but the sleep goal is about weeknights. | Assume oldest → newest, ending on the anchor date. The synthetic data gets real dates. |
| C10 | SPEC_REVIEW §1.8 implied a hinge exclusion would catch hip thrusts. The catalog has no hinge pattern, and hip-thrust-style work is labeled "hip lift". | Fixed in SPEC_REVIEW. See D5.2. |
| C11 | SPEC_REVIEW §3.1 expected a count mismatch. | Fixed in SPEC_REVIEW: the counts match. |
| C12 | The member's timezone is America/Los_Angeles, and the coach's may differ. | Compute "yesterday" and "this week" in the member's local time from the anchor date (§2.8). |
| C13 | Our early framing was "avoid the injured joint". Published guidelines say the opposite: load it progressively. Hip and knee exercise is Grade A for patellofemoral pain (PFP), exercise is Grade A for chronic low back pain (LBP), and progressive resistance is Grade A for rotator cuff. | See D2. Exclusions are rare and stage-specific. The default is allow or down-rank with a cue. |

## Decisions

### D1 ✅ Synthetic catalog extension and deadlift family (§1.8)
- **User experience:** "Exclude deadlifts" visibly works, and knee-safe plans aren't repetitive.
- Keep `exercises.json` untouched. Add `exercises_synthetic.json` in the same schema, with each entry tagged `source: synthetic`.
- The extension covers the deadlift family, the exercises in the member's history, and knee-safe alternatives. Add more only when a decision exposes a gap.
- A `variant-of` edge links each exercise to its family. "Exclude deadlifts" removes the family; "no hinging" removes the whole hinge pattern.

### D2 ✅ Injury rules live on Condition nodes in KG1; a member's injury is `instance-of` a Condition (§1.6, §1.7, §2.4)
- **User experience:** the coach gets plans that match current rehab practice. The injured area is trained with appropriate cues (box squats stay, with a cue), and only the specific risky loads are removed (jumps, deep loaded flexion). The plan never bans the knee outright.
- **Load and include everything (confirmed 2026-10-15):** every injury, condition and relevant clinical detail the member has (care-team notes, status, side, onset date, complaints raised in chat, by the coach, or in a day-of check-in, see D12) is loaded into KG2 and drives the plan. Nothing is silently dropped. An injury the system can't map to a Condition still blocks generation until the coach confirms (§1.1). Injured regions are *trained*, not avoided, under the evidence-based default below.
- **Mechanism vs. content:** the mechanism is ours. The clinical content is data, and each rule carries `source`, `owner`, `confidence` (guideline-stated / practice-consensus / our-inference) and `review_status` ("unreviewed – requires clinician sign-off").
- **Evidence-based default (C13):** most rules are *allow* or *down-rank with a cue*. Hard exclusions are rare, tied to injury stage, and flagged as our inference wherever no guideline states them.
- **Jordan's two hard exclusions** (plyometric/impact, and deep loaded knee flexion) come directly from her care-team note. That note is the cited source for them.
- **Status semantics:** contraindications are always hard-excluded while the injury is active. Status changes only how plain `stresses` edges are treated:
  - acute → exclude
  - recovering → down-rank with a modification cue
  - cleared → injury inactive
- **Rules point at movement patterns,** with narrower sub-patterns where the catalog is too coarse (deep loaded squat vs. box/partial squat).
- **Load-type vocabularies** come from the research doc §3. For the knee, `open_chain` is split into `open_chain_terminal` and `open_chain_midrange`. The two peak patellofemoral stress at different angles (squat at 60–90°, leg extension at 0–30°), so a single tag would contradict the source. The lumbar and shoulder vocabularies have 6 values each, including positive tags (`isometric_bracing`, `rotation_neutral`) that rules can rank up.
- **Thresholds are parameters, not facts.** Knee-angle windows (0–45° squat, 90–45° leg extension) come from one small biomechanics study (Powers 2014, n=10 healthy). The pain-monitoring limit (sources range from ≤2/10 to <5/10, settling by the next day) is a clinician-owned parameter. Both are stored as configurable rule parameters with citations, not hard-coded.
- **Edge direction:** Pattern → contraindicated-for → Condition. This is the normal clinical reading and the reverse of the spec's arrow; documented.
- `part-of` is traversed in both directions (§1.4). An ad-hoc complaint ("bothering her") is treated as acute and fails closed (§1.1).

### D3 ✅ Laterality: whole-joint safety, side stored on the injury (§1.5)
- **User experience:** a mislabeled side can never undermine safety, and the coach still sees "left knee" in the trace and cues.
- The safety filter ignores an exercise's `side`. Laterality lives on the member's injury in KG2, following SNOMED's laterality-qualifier pattern.
- Side is used for the provenance trace, modification cues, and logged coach overrides.
- Ingestion renames the field to `unilateral`, and `bilateral_pair_id` becomes a `paired-with` edge. Unilateral exercises display as "each side".

### D4 ✅ Equipment feasibility and substitution (§1.8, §1.9)
- **User experience:** "No barbell, only DBs and a KB" produces a full plan with sensible swaps, not a gutted plan and not one that still needs a bench.
- An equipment concept graph decides feasibility:
  - `broader` hierarchy (EZ Bar and Trap Bar → Barbell family)
  - `provides` edges (Adjustable Bench → flat/incline/decline)
  - SKOS exact/close matches (Miniband ≈ Loop Band, flagged)
  - ambient items (Wall, Floor; Floor ≈ Mat as a flagged closeMatch)
- `requires` has AND semantics and carries a quantity (a single KB rules out double-KB exercises).
- Substitution is computed from a shared movement pattern plus muscle overlap. Authored `substitutes-for` overrides win. Substitution always runs **after** the safety filter, with its own test.
- If no equivalent exists, use a partial substitute that works the same muscles, labeled as such. If nothing clears the minimum score, drop the slot and say so.
- **Equipment source priority:**
  1. The coach's in-session statement, or the member's day-of check-in (D12): the full set for that plan only; the profile is unchanged.
  2. The profile.
  3. Where the profile conflicts with the member's chat, the copilot flags it ("Profile lists a bench, but on 05-22 she said only DBs and a KB. Confirm?").

### D5 ✅ Product behaviors from the data review
1. **Readable data model.** Ingestion normalizes `is_bilateral` → `unilateral`, fixes the duplicated joint, and fills the two empty `joints_loaded` from movement-pattern defaults. Each fix is logged in provenance.
2. **Hinge pattern.** A "lower pull - hinge" pattern node is added for the synthetic deadlift family and documented as a taxonomy addition.
3. **Honest churn.**
   - Compute churn from completed weeks only, and show the current week as "in progress (2 of 7 days)".
   - Show the evidence next to the score: adherence trend, skipped sessions with stated reasons, message frequency, sleep.
   - When the computed risk disagrees with the provided brief, the copilot says so and explains why.
4. **Preferences vs. rules.**
   - Dislikes down-rank; they never hard-exclude. A disliked exercise that is the best safe option can still appear, flagged with the conflicting evidence.
   - Only an explicit coach instruction or a safety rule hard-excludes.
5. **Grounded copilot.**
   - For claims that matter (pain, injury status, progress), the copilot quotes or cites the member's own words and dates, e.g. "She said her knee 'felt okay' with box squats (06-03)", not "pain-free".
   - Every claim links to its source node in KG2. Tested.
6. **Realistic session length.**
   - The default time window is her recent actual session length (about 30 min), with her 50 min preference shown alongside. The coach can change it in one click.
   - A persistent gap between preferred and actual length is surfaced as a churn/readiness signal.
7. **Pronouns.** The synthetic profile gets an explicit `pronouns` field. The UI and copilot use it rather than inferring from `sex`.

### D6 ✅ SNOMED CT usage and storage (§3.6)
- **User experience:** each injury in the trace shows a real clinical code (e.g. "Patellofemoral pain → SNOMED 430725003"), next to our own label.
- **Commit only:** bare codes, our own labels, the edition/version string (SNOMED CT US 2026_03_01), and a NOTICE file.
- **Never commit:** SNOMED descriptions or relationships. The app shows our own labels; official names are only in the private research note.
- **As built (2026-10-16):** a runtime lookup of official names from NCI EVS was planned and not built. Codes plus our labels were enough for the trace, and the lookup would add a network call to the request path.
  - Treating bare codes as low-risk is our inference. No official statement was found; documented.
- **Our own part-of hierarchy.** The EVS API exposes no direct part-of links (the knee goes through 244548003 "Component of knee joint"). Every part-of edge is hand-authored, with SNOMED codes attached as `skos:exactMatch`.
- **Codes verified live:**

  | Concept | Code | Note |
  |---|---|---|
  | Patellofemoral pain syndrome | 430725003 | |
  | Low back pain | 279039007 | |
  | Disorder of rotator cuff | 414033006 | The narrower 789754007 is modeled as acute inflammation, a poor fit for tendinopathy |
  | Knee meniscus | 43653007 | 432750007 "Meniscus" is a bacterial genus — a resolver trap and a good test case |

  The full table is in the research doc.

### D7 ✅ Ontology alignment: EXMO first, COPPER as backup, our own schema for gaps (§3.5)
- **User experience:** invisible to the coach day to day. Each concept in the trace can link to a published ontology term, which makes the system auditable and portable.
- **Priority order for mapping each concept:**
  1. **EXMO** (CC BY 4.0, OBO PURLs) for exercise types, equipment and injuries. Mapped with `skos:exactMatch` / `closeMatch`.
  2. **COPPER** (and the BCIO classes it reuses) for member-graph personalization and behavior-change concepts, used only where EXMO has nothing: adherence, goals, motivation, churn signals.
  3. **SNOMED CT** codes for clinical conditions and anatomy (D6).
  4. **Our own schema** for everything else, notably the `stresses`, `contraindicated-for`, `variant-of`, `substitutes-for`, `provides` and `paired-with` relations, load types, and the movement-pattern taxonomy.
- **OPE** is not used. It couldn't be obtained (BioPortal key wall plus a Cloudflare block, no mirror found; a 2013 alpha with no license). The README records the attempt.
- Every mapping is verifiable: we link only to IRIs we have resolved. Anything unverified stays as our own term, with no mapping.
- **As built (2026-10-16):** 47 EXMO/NCIT mappings in `kg/ontology_alignment.ttl`, each checked against the current `exmo.owl` release (exists, label matches, not deprecated). **COPPER is not mapped**: its own IRIs use a non-resolvable base (`http://COPPER/ontology/COPPER_`), so they fail the "only IRIs we have resolved" rule, and the license is non-commercial. Member-graph concepts stay in our schema. The safety filter never reads these mappings: equipment `closeMatch` expansion only follows our own equipment nodes (tested).

### D8 ✅ Resolver: two extractors in parallel, union, ask on disagreement (§1.1, §1.3, §3.4)
- **As built (2026-10-16), the embedding pass:** fastembed with `bge-small-en-v1.5`. It is narrower than first planned, because calibration showed filler words score high against regions and equipment ("full" → full body 0.86):
  - it only considers muscle and structure concepts;
  - a match needs ≥ 0.78 and a 0.03 margin over the next different concept;
  - in a sentence with a safety word it never resolves, only adds a suggestion to the blocking question;
  - words that extend a body-part label ("kneeling") skip it.
- **User experience:** coaches type naturally ("keep it easy on her knee", "she's been babying that shoulder"). A missed or misread injury can only make the plan *more* cautious, never less. When the system can't resolve a safety term, it asks instead of guessing.
- **Extraction:** a rules extractor (cue lexicon + phrase chunking) and an LLM extractor (structured `{text, role, negated}` mentions) run in parallel. Their mentions are unioned. The LLM never chooses concepts.
- **Matching:** each mention runs through exact → fuzzy → embedding matching against SKOS labels stored in the graph (prefLabel / altLabel / hiddenLabel, including slang like "pecs" and "DBs" and common misspellings). Fuzzy matching is restricted by concept type and uses whole-word boundaries ("back" ≠ "back squat"; "knee" ≠ "kneeling"). Embeddings are only a final fallback.
- **Safety rules, all deterministic:**
  - If either extractor flags a body-part or condition term as a constraint, it is treated as a constraint.
  - A polarity conflict between extractors resolves to constraint, and the trace says why.
  - A safety cue word with no resolved constraint blocks generation: "Couldn't resolve *X* — confirm?"
  - Goal/target terms fail open: the plan falls back to a general plan, and the unresolved term is noted.
- **"My" = the member** (§3.4).
- **Logged per request:** which extractor caught each mention, which match pass fired, and the confidence. These are aggregated into a pass-frequency report, which shows embeddings are a fallback, not the main method.
- **Latency (user condition: must not hurt latency):**
  - The two extractors run in parallel. The rules extractor takes milliseconds, so the cost is just one small LLM call on a fast model (target < 1 s).
  - LLM extraction has a hard timeout (~1.5 s). On timeout or error, the resolver proceeds rules-only. That is safe because rules are the safety floor. The trace notes "LLM extraction skipped (timeout)".
  - Concept embeddings are precomputed at build time, and only unresolved mentions are embedded at runtime.
  - Estimated budget: extraction ~1 s + graph resolve/filter/score < 100 ms + plan composition ~2–3 s (streamed) ≈ 3–4 s, against the ~5 s target. These are estimates; per-stage latency is measured and reported (§2.3).
- **Offline / no API key:** rules-only extraction. It is fully safe, with lower language coverage.

### D9 ✅ Plan composition: LLM picks by ID, validator checks, deterministic builder as fallback (§1.2)
- **User experience:** the coach always gets a safe plan. Usually it is LLM-composed, with natural ordering and coaching language. When the LLM is unavailable or its output fails validation, a deterministic plan is built instead, and the trace says which builder produced it.
- **Primary path (LLM):** the LLM receives only the filtered, scored candidates, each with an ID. It must return structured output in which exercise IDs are an enum of those candidates, so it can't name anything else. Display names always come from the graph.
- **Deterministic validator (always runs).** Each item must:
  - exist in the catalog and in the filtered safe set
  - have equipment and quantity that are feasible
  - not duplicate another item

  The plan as a whole must fit the time window. Each violation is repaired with a D4 substitute, or the item is dropped. Every repair is logged in the trace ("validator replaced X: reason").
- **Fallback path (deterministic builder).** Code picks exercises, sets, reps, rest and order from the scores and templates. The LLM, when available, only writes cues and the rationale. The fallback is used when:
  - there is no API key (offline mode)
  - the LLM call times out or errors
  - the LLM output fails validation twice
- **User preference noted:** the deterministic element is valued. LLM composition is used because it improves the product, and the deterministic builder stays first-class: tested, and runnable on its own.

### D10 ✅ Multi-agent shape: a deterministic spine, a router, three agents, and model tiers (§2.1, §2.3)
- **User experience:** simple questions come back almost instantly. Workout requests arrive within the ~5 s budget. Open-ended analysis is deeper and streams as it works. Whichever route a request takes, any exercise shown has passed the same safety gate.
- **Deterministic spine (shared services, not agents):** the resolver (D8), the safety filter and scorer (D2–D4), the readiness/stage rules (D11), the validator (D9), and the provenance recorder. Every route that outputs exercises must pass through the same gate, so a misroute can only produce a worse answer, never an unsafe one.
- **Router (a component, not an agent).** Routing reuses the LLM call we already make, so it costs nothing extra:
  1. Rules decide the obvious cases instantly ("build", "workout" or a time window → Composer; a single-metric question → Lookup).
  2. Otherwise, the D8 extraction call also returns `intent` + `confidence`, so routing adds no extra hop or model.
  3. Low confidence, or a rules/LLM conflict → route to Analyst (the broadest route), or ask the coach.
  4. Offline → rules only.
- **Three agents, each with one job:**
  - **Composer:** builds workouts (D9).
  - **Lookup:** answers single-fact questions from a template or a single KG2 query, with no LLM or a small one.
  - **Analyst:** open-ended investigation with KG2 tools and charts. Its loop is capped (~3–4 steps). On reaching the cap, it answers with what it has, states what it didn't reach, and offers "keep digging".
  - A mixed request ("why is she slipping, and build her something easier") becomes a planned sequence: Analyst → Composer.
- **Model per route, with a fallback chain:** small/fast model for extraction, routing and Lookup → mid model for Composer → strongest model for Analyst. The deterministic builder is the floor.
- **Revised after the first real-model eval run (2026-10-15):** the Composer on the mid tier took 8–16 s, and the Analyst on the large tier took up to 25 s. Both are far over the ~5 s target. Defaults are now Composer = small tier and Analyst = mid tier, configurable via `FC_COMPOSE_TIER` / `FC_ANSWER_TIER`. Quality is held by the same validator and grounding checks, and the eval gate tracks both latency and the LLM-path rate. The same run found that Claude 5.5 rejects `temperature=0`: unsupported params are now dropped.
- **One shared provenance recorder:** every agent and service writes to the same trace, so nothing is passed by hand between hops. The routing decision and its confidence are shown in the trace.
- **Rejected:** a fourth "orchestrator" agent. It would add a hop and nondeterminism ahead of the safety path. Also rejected: a "safety agent", since safety must stay deterministic.
- **LAYA (considered, deferred).** An Apache 2.0 small-classifier family (~420M params, ~33 ms on GPU, ~200–460 ms on CPU), supported by LiteLLM's auto-router. Deferred because:
  - It is weak zero-shot; its own README says it is a base to fine-tune, and that needs ~30k labeled examples.
  - It is slow on CPU.
  - It adds a model download and a classifier server, which conflicts with "one command to run".

  Every routing decision is logged with its features and outcome. That becomes the labeled dataset for a fine-tuned LAYA router in production.

### D11 ✅ Longitudinal signals: one job per timescale, deterministic rules (§2.10)
- **User experience:** every adjustment to the plan is explained in plain words in the trace, e.g. "Intensity capped at RPE 6: slept 4 h last night vs. her 6.4 h average." Labs never silently change a session. A good night's sleep never makes a rehab plan more aggressive.
- **Each signal has one job:**

  | Signal | Changes over | Job | Effect |
  |---|---|---|---|
  | Sleep / HRV / resting HR (device or self-report, D12) | Days | **Readiness** | Sets today's intensity/volume cap |
  | Adherence / workout history | Weeks | **Volume & progression** | Hold, progress, or regress; favor familiar exercises when adherence slips |
  | Labs / DEXA | Months | **Context only** | Goals and copilot talking points. Never changes today's plan; surfaced only as "worth raising with her care team" |
  | Journey stage | Months | **Complexity & tone** | See the stages below |

- **Readiness rules:**
  - Readiness can only *lower* intensity or volume, never raise it above the plan's normal level.
  - Baselines are personal: a rolling 28 days for readiness, 4 completed weeks for adherence.
  - Cold start: new members use conservative population defaults, or their self-reported typical values (D12), until about 14 days of data exist.
- **Journey stages,** assigned by deterministic rules from tenure, history and adherence:
  - **Onboarding** (under ~4 weeks): simple, low-skill exercises; conservative loads; more cues.
  - **Building:** normal progression.
  - **Established:** more variety and challenge.
  - **At-risk** (adherence dropping): shorter sessions with familiar, achievable exercises. The copilot leads with a win.
  - **Rehab** (active injury): can combine with any stage above; D2 rules apply.
  - Jordan = Established + At-risk + Rehab.
- **Thresholds are parameters** ("reduced" sleep, "at-risk" adherence, and so on). They are documented, and the coach can override them in the prompt.
- The Composer (D9) works *inside* the caps these rules compute; it never sets them.

### D12 ✅ Member check-ins: day-of and baseline self-reported data feed the pipeline
- **User experience:** the member (or the coach on their behalf) can say "baby was up all night, I slept 4 hours", and today's plan adapts automatically. The adjustment is visibly flagged to the coach.
- **Two kinds of input:**
  1. **Day-of check-in** (optional, ~30 seconds), as structured fields:
     - sleep last night (h)
     - energy (1–5)
     - soreness (1–5)
     - pain in any known injured area (0–10)
     - stress (1–5)
     - time available today
     - equipment today
     - a free-text note
  2. **Baseline self-reports:** typical sleep per night, typical session length, and similar. These fill gaps where there is no device data, and are used for cold start (D11).
- **The free-text note goes through the same resolver as coach prompts (D8).** For example, "baby up all night, slept 4h" yields sleep = 4 h, with the cause recorded as context (one-off, external). "Knee's a bit cranky" yields a complaint on the knee, which feeds D2.
- **Storage:** every entry becomes an `Observation` node in KG2 with a value, a timestamp, `source` (self-report / coach-entered / device), and provenance. Nothing is overwritten. Today's entry sits alongside the history.
- **Precedence for today's plan:** today's check-in > device data from last night > personal rolling average > self-reported typical value > population default. The trace states which source was used.
- **Flags.** These are deterministic, and the thresholds are parameters:
  - **Sleep well below personal baseline** (e.g. 4 h vs. a ~6.4 h average): readiness is "low". The plan is shortened and capped at a lower RPE, or swapped for a light mobility/technique session, and the coach is flagged.
  - **Pain at or above the clinician-set limit in a known injured area:** that injury is treated as *acute for today* (fail-closed, D2), and the coach is flagged. If pain is reported in a new area, it is handled as an unresolved complaint and generation asks for confirmation (§1.1).
  - **Low time or different equipment:** this sets the time window or equipment for this plan only (D4, D5.6).
  - **A one-off cause** (e.g. "baby up all night"): recorded as context. It counts in the rolling average but is labeled, so the copilot can distinguish a rough night from a sleep trend.
- **Check-ins can only lower readiness or add constraints.** They never loosen a safety rule.
- **No check-in today:** the plan uses the next source in the precedence order, and the trace says "no check-in today".
- **Scope for the take-home:** a check-in panel in the coach dashboard ("Log check-in for Jordan"), plus the same API endpoint a member app would call. A member-facing app is out of scope and documented as such.
- **Synthetic data:** the expanded history includes some check-ins, including one rough-sleep night, so the behavior is visible in the demo.

### D13 ⏳ Async member messages: more data for the same pipeline
- **User experience:** a trainee can message hours before a session ("knee's cranky today", "only have 20 min", "at a hotel gym"). By session time the plan already reflects it, and the coach sees what changed and why.
- **Intake:** each message is stored as a `Message` node in KG2 (timestamp, author, source = member-async). Its text goes through the same resolver as check-in notes and coach prompts (D8), and the extracted facts become `Observation` nodes linked to the message for provenance.
- **Re-plan on new data:** if the member has a session scheduled today or tomorrow and the message changes any input (readiness, constraints, time, equipment), the pipeline re-runs automatically.
  - Plans are versioned; nothing is overwritten.
  - The coach sees a diff: "Plan v2: swapped split squat for glute bridge, because the member reported knee pain 6/10 at 7:40am."
  - New data can only make the plan more cautious, never less (same rule as D12).
- **Flags to the coach:** the same deterministic thresholds as D12. Pain in a known injured area or a new body area, and very low readiness, are flagged immediately.
- **Replies to the member (⏳ default pending confirmation):** a deterministic acknowledgement only, e.g. "Got it, today's session has been adjusted to 20 min." Anything clinical (pain, a new injury) gets "Your coach has been notified." No AI-generated health advice goes to members.
- **Feeds the copilot:** async messages become real data for "message pattern" (§2.11) and churn signals (D5.3), e.g. message frequency and who initiates.
- **Scope for the take-home:** a messages endpoint, plus a simulated member inbox in the dashboard to demo it. A member-facing app is out of scope.

### D14 ✅ Time window (§2.6)
- **User experience:** "30 min" yields a plan that really fits in 30 minutes, including the warm-up.
- **Interpretation:** a time window is a duration, not a clock window.
- **Plan length is computed deterministically:** sets × (work + rest) + transitions, plus a short warm-up.
- **Timed holds:** planks and carries are prescribed as `duration_s`, not reps.
- **Over-time plans:** the validator (D9) trims accessory work first. The warm-up is never trimmed.
- **Default time window:** the member's recent actual session length (D5.6), unless the coach or a check-in (D12/D13) says otherwise.

### D15 ✅ Graph store: embedded Oxigraph (pyoxigraph), RDF-native
- **User experience:** reviewers run one command, with no Docker and no database server. Clinical rules and anatomy are readable `.ttl` files, so a rule change shows up as a reviewable diff.
- **Both KGs live in one Oxigraph store,** in separate named graphs (KG1 domain, KG2 member). The source of truth is committed Turtle files, loaded at startup.
- **Native fit:** SKOS labels, PROV-O traces and EXMO/SNOMED links are plain triples. Two-way `part-of` traversal is a SPARQL property path (`:partOf*` / `^:partOf*`).
- **Edge properties** use the n-ary relation pattern. For example, a `Stress` node carries exercise, structure, `load_type` and provenance. That gives each rule and annotation its own provenance anchor.
- **Time series:** observations are stored as RDF. Rolling averages and other aggregates are computed in Python, which is fine at this scale.
- **Runtime writes** (check-ins, messages, plan versions, PROV traces) are appended to an event log (`var/events.jsonl`) and replayed into the store at startup. This is simpler than persisting the store, and keeps every input append-only. A "reset demo data" action clears the log and replays the scenarios cleanly.
- **Rejected:**
  - Neo4j: requires Docker, plus an RDF translation layer (neosemantics).
  - Kùzu: Apple acquired it and archived the repo on 2025-10-10, so it is effectively unmaintained.
  - NetworkX + SQLite: no query language; it undercuts the KG claim.
- **Not verified:** whether pyoxigraph exposes RDF 1.2 features. The design doesn't depend on them.

### D16 ✅ Backend and frontend
- **Backend:** Python + FastAPI.
  - Graph store: `pyoxigraph`.
  - Fuzzy matching: `rapidfuzz`.
  - Structured-output schemas: `pydantic` (D9).
  - Async handles the parallel extractors (D8), and plans stream back via SSE.
  - Tests: `pytest`.
  - Endpoints include generate, copilot, check-in (D12), messages (D13), trace and reset-demo.
- **Frontend:** React (Vite) + Tailwind. Charts use Recharts. An optional small force-directed view renders a plan's provenance path. The frontend is built to static files and served by FastAPI.
- **Running it:**
  - `make dev` runs both.
  - `docker compose up` is optional and never required.
- **Rejected:**
  - TypeScript end-to-end: thinner graph and fuzzy-matching tooling.
  - Streamlit/Gradio: reads as a prototype, with weak layout control.
  - Next.js: a second server, plus SSR we don't need.

### D17 ✅ LLM access: LiteLLM (Python SDK, in-process) with tiered models and cross-provider fallback
- **User experience:** if a provider is slow or down, the request falls back to another provider before dropping to the deterministic builder, so the coach rarely sees a degraded plan. Cost and latency per request are visible in the trace.
- **LiteLLM is used as a library, not a proxy server.** That means no extra service to host, and "one command to run" still holds.
- **Tiers (D10)** are set in config, as model per tier plus a fallback list. Example:
  - Primary: Anthropic `claude-haiku-5-5` (extraction/routing/Lookup), `claude-sonnet-5-5` (Composer), `claude-opus-5-5` (Analyst).
  - Fallback: the equivalent OpenAI tier.
  - Final floor: the deterministic path (D8 rules-only, D9 builder).
- **Keys:** works with either provider key alone. With no key, the app runs in offline mode.
- **Embeddings:** a small local ONNX model via `fastembed` precomputes concept embeddings, used only as the resolver fallback. It needs no key and works offline.
  - Chosen over sentence-transformers because that pulls in PyTorch (~1–2 GB). fastembed keeps the deployed footprint around ~100 MB for embeddings.
- **Cost:** LiteLLM's core is MIT-licensed, with no per-token markup. Provider tokens are billed at the provider's normal rates. Fallback calls only happen on failure, so cost is effectively the same as calling one provider directly. The paid enterprise tier (SSO, team budgets, RBAC) isn't needed.
- **Risks / mitigations:**
  - Structured-output behavior varies by provider, so D9's strict schema is tested against each configured provider.
  - The dependency is pinned and audited; a past LiteLLM security incident is noted.
  - Provider-specific features such as prompt caching need to be verified as passing through.
- **Observability (no conflict):** there are two separate layers.
  1. **Provenance trace (PROV-O):** why an exercise was chosen or excluded. This is written by our shared recorder and is independent of LiteLLM.
  2. **LLM call telemetry:** latency, tokens, cost, errors. This is captured with a LiteLLM custom callback that writes into the same request trace, keyed by a `request_id` passed in call metadata.
  - **Every fallback attempt is recorded,** not just the final one: provider, model, error and latency. The trace always shows which model actually answered.
  - **Streaming:** token usage and cost are recorded when the stream completes.
  - **Cost accuracy:** LiteLLM's built-in price map may lag new models, so per-model prices are checked and overridden in config if they're missing.
  - **Privacy:** telemetry stays local (our store + stdout / optional OpenTelemetry). Prompts containing member data are not sent to third-party observability services by default. In production, use a self-hosted or redacting sink.
- **Future:** this is where a fine-tuned LAYA router plugs in (D10).

### D18 ✅ Observability and evals, mirroring the clinical-copilot (OpenEMR) project setup
- **User experience:** every request can be opened as a trace that shows what was resolved, what was excluded and why, which models ran, and their latency and cost. Every change runs against golden sets, and safety regressions block the merge.
- **Three layers, one request ID:**
  1. **Provenance (PROV-O):** the domain "why". Lives in the graph and is rendered in the UI's trace drawer.
  2. **Tracing:** OpenTelemetry spans for every pipeline stage (route, extract, resolve, filter, score, compose, validate). LLM calls are captured with the LiteLLM callback, which records provider, model, attempt number, tokens, cost and latency.
  3. **Evals:** golden sets, run with `make eval`.
- **Trace backend:**
  - **Default:** Langfuse, which LiteLLM supports natively. It covers traces, prompt versions, datasets and LLM-judge scores.
  - **Hosting:** the cloud free tier is acceptable here because all data is synthetic. Production would self-host, because Langfuse self-hosting needs Docker services, which conflicts with "one command".
  - **No Langfuse keys:** spans go to local JSON logs, and the app runs unchanged.
- **Metrics reported:**
  - per-stage latency p50/p95, against the ~5 s budget
  - which resolver pass fired, as a frequency
  - routing intent and confidence
  - fallback rate
  - validator repair rate
  - fail-closed ("please confirm") rate
  - cost per request
- **Eval mode** disables provider fallback, sets temperature to 0 where supported, and records the exact model and version. Prompts are versioned files.

#### Golden sets (planned, to be authored during the build)
| Set | Size (target) | Built from | Scoring | Gate |
|---|---|---|---|---|
| **Safety scenarios** | ~25 | The spec's 3 required scenarios, plus the traps: part-of up/down, laterality, fail-closed, deadlift family, single KB, pain-in-check-in → acute, new-area pain → ask | Deterministic asserts on the excluded set and the trace reasons | **100%, blocks merge** |
| **Validator red-team** | ~10 | Injected hallucinated IDs, excluded exercises, infeasible equipment, time overruns | Must be caught or repaired | **100%, blocks merge** |
| **Resolver** | ~60 phrases | "back" vs "back squat", "knee" vs "kneeling", bacterial "Meniscus", slang (pecs, DBs), misspellings, negation/polarity, "my" = member | Concept + role + polarity precision/recall, per extractor and per match pass | Precision on constraints = 100%; others tracked |
| **Router** | ~30 | Lookup / Composer / Analyst / mixed / ambiguous prompts | Accuracy + confusion matrix | Tracked; misroutes can never be unsafe (D10) |
| **Check-in / async extraction** | ~20 | "baby up all night, slept 4h", "only 20 min", "hotel gym", "knee cranky 6/10" | Extracted observations match expected | Tracked |
| **Composer quality** | ~12 requests × 3 members | Spec prompts + journey stages (onboarding / at-risk / established) | Rule checks (fits time window, pattern balance, no repeat of yesterday, honors caps) + LLM-judge rubric | Rule checks 100%; rubric trended |
| **Copilot grounding** | ~20 questions | Spec copilot questions + traps (partial-week churn, "pain-free" vs "felt okay", relative dates) | Every claim cites a KG2 node; quotes match the source; numbers recomputed | Citations/quotes 100%; rubric trended |

- **Golden sets are versioned JSON** in `evals/`. Each case records why it exists (which trap or decision it covers).
- **CI (GitLab):** safety, validator and resolver-constraint suites run on every commit, with no API key needed. LLM suites run on demand and post a report table that feeds the README.

#### Carried over from the clinical-copilot (OpenEMR) project
Source: `~/Desktop/clem-week2-combined`, files `EVAL_GATE.md`, `KEY_METRICS.md`, `COST_ANALYSIS.md`, `clinical-copilot/app/observability.py`, `clinical-copilot/evals/`. The same patterns are reused here, also on GitLab CI (the repo lives at labs.gauntletai.com/taylorclements/future_coach):
- **Observability module:** a `RequestObserver`, modeled on `TurnObserver`.
  - Langfuse is used only if keys are set (lazy import). Otherwise every call degrades to structured JSON logging via `_log()`, which always runs.
  - Spans cover workers, LLM calls and tool calls. Routing decisions and validation results are logged as events.
  - Each request gets a correlation ID. Coach feedback (👍/👎 on a plan) attaches as a Langfuse score.
- **Prompts:** plain constants committed in code, listed in a prompt table in `EVAL_GATE.md`. They are not loaded from Langfuse.
- **Golden set:** `evals/cases.py`, where each case has its own `check()`.
  - Fixtures are generated programmatically and seeded by `evals/seed_fixtures.py`.
  - Case counts per category are documented in `COVERAGE.md`, with failures written up in `ERROR_ANALYSIS.md`.
- **Gate logic (`evals/gate.py`):** two checks, and both must pass.
  1. Every case's `check()` passes.
  2. Rubric metrics stay at or above their floors, and no metric drops more than 5% relative to the committed `baseline_results.json`.

  A metric is `None`, not 0, for cases it doesn't apply to. The baseline is only ever updated by a human commit.
- **Rubric metrics (floor 100%):**

  | Metric | Meaning here |
  |---|---|
  | `schema_valid` | Plan, copilot response and trace objects validate (pydantic) |
  | `safety_respected` | No excluded or contraindicated exercise, or infeasible equipment, in the final plan |
  | `citation_present` | Every copilot claim cites a KG2 node, and every plan exercise has a provenance path |
  | `grounded` | Quoted member words and numbers match their source nodes |
  | `fail_closed` | A named set of cases whose correct behavior is to ask or decline (unresolved injury, new-area pain, etc.) |
  | `no_member_data_in_logs` | The fixture member's name and free-text notes never appear verbatim in local log lines. The data is synthetic, but the discipline carries over to production |

- **CI jobs (`.gitlab-ci.yml`):**
  - `eval_unit_tests`: LLM-free (safety, validator, resolver constraints). Runs everywhere, including draft PRs.
  - `eval_golden_set`: real LLM calls. Runs on non-draft PRs that touch app or eval code. `retry: 1` absorbs phrasing variance. Blocks merge through branch protection.
  - Superseded runs are cancelled (`interruptible: true` + `workflow.auto_cancel`). Draft MRs get a blocking `eval_gate_pending` job, as in the clinical-copilot repo.
  - A `FORCE_FULL_EVAL` manual trigger is available.
- **Metrics doc (`KEY_METRICS.md`):** one North Star, a few supporting metrics, and an anti-gaming guard.
  - **North Star:** *safe-grounded plan rate*, the % of plans that pass the validator with no repair and with full provenance.
  - **Supporting:** p95 latency per route; fail-closed rate; provider fallback rate; cost per request.
  - **Anti-gaming guard:** *plan fill ratio*, i.e. exercises and minutes delivered vs. requested. An empty plan is trivially "safe", so this keeps the North Star honest.
- **Companion docs:**
  - `EVAL_GATE.md`: locations, trigger, gate logic, environment, fresh-clone path.
  - `EVAL_RESULTS.md`
  - `COST_ANALYSIS.md`: dev spend, cost per request from real `cost_usd`, projections at 100 / 1k / 10k / 100k users.
  - `PERFORMANCE_BASELINE.md`, plus a Locust load test.
  - `THREAT_MODEL.md`

### D19 ✅ Small defaults confirmed (D13, §2.11, §2.12)
- **Replies to the member (D13):**
  - The member gets a fixed acknowledgement only, e.g. "Got it — today's session is now 20 min."
  - For pain or injury, the reply is only "Your coach has been notified."
  - The system never generates its own health advice for members.
- **Message pattern (§2.11):** a chart of member-initiated messages per week, plus who initiates (member vs. coach).
  - Chosen because a drop in member outreach is an early churn signal.
- **Excluded exercises (§2.12):** each excluded exercise is recorded as a PROV-O entity produced by the `SafetyFilter` activity, with its reason.
  - Example: "Static Jump — plyometric, contraindicated for left-knee patellofemoral pain."
  - The UI shows a one-line summary (e.g. "4 excluded for knee safety") that expands to the full list.
- **Docs:** no separate ARCHITECTURE/PLAN docs. This log is the working record, and the README is written from it at the end.

### D20 ✅ Making the graph visible (2026-10-16)
- **User experience:** the coach can see *why* in the shape it was decided: an exercise's load on a structure, up the part-of hierarchy, to the condition and the rule. The member's own graph shows what the system knows about them and which domain concepts that touches.
- **Plan graph:** the safety filter's recorded paths, returned as typed nodes and edges with each generated plan, split into tabs by reason (injury rules, why picked, exercise family, equipment).
- **Member graph:** read by SPARQL across KG2 and KG1 at request time. Goals and equipment were added to KG2 so the view reads the graph, not the JSON.
- **Layout:** a deterministic column layout (one barycentre sweep), not a force-directed one. The same plan always draws the same picture, which matters when a coach compares two versions. No graph library was added.
- **Pictograms:** chosen by the backend from the exercise's movement patterns (most specific first, tested so every catalog exercise gets one) and drawn from a fixed SVG library. No images are generated.
- **Images in chat:** the provided data has an image attachment with a caption but no file. It is shown as a clearly labeled synthetic illustration, named by convention (`<member>-<date>.svg`), so the provided data stays untouched.

## ⚠️ Changes required for commercial use

This project is non-commercial, so the following is acceptable here but must change before any commercial use:

| Item | Issue | Required change |
|---|---|---|
| **COPPER** | Licensed CC BY-NC 4.0, i.e. non-commercial only. Not mapped today (see D7). | Before adding any mapping, map to the BCIO classes instead (verify the BCIO license first), or obtain a commercial license from the COPPER authors. |
| **SNOMED CT** | Use requires an Affiliate license in most countries. The US is covered via an NLM UMLS license, which has its own terms. Our bare-codes-only approach is an inference, not confirmed. | Confirm licensing with SNOMED International / NLM before shipping. Register as an affiliate if needed. |
| **Clinical rules** | All rules are `unreviewed`; thresholds come from small studies. | A clinician owns and signs off the rule table, with an audited review workflow. |

## Open queue
- None. D1–D20 are decided and built.
