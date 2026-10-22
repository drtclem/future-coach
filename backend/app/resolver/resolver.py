"""Resolve a coach's request onto canonical graph concepts (D8).

Two extractors feed one deterministic matcher:
  * the rules extractor (this module) -- always runs, works offline, is the safety floor
  * an optional LLM extractor that only proposes mentions {text, role, negated};
    it never chooses concepts (wired in slice 4)

Each mention is matched exact -> fuzzy -> embedding against SKOS labels in the
graph, restricted by the concept types its role allows. Safety rules:
  * a body part / condition flagged as a constraint by EITHER extractor is a constraint
  * a polarity conflict resolves to the cautious role
  * a safety cue with nothing resolved behind it blocks generation (fail closed);
    an unresolved goal only falls back to a general plan (fail open)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from ..graph.ns import FC, FCA, FCC, local
from ..graph.store import DomainGraph
from ..safety.filter import Constraints, Injury
from . import embed

TYPES = {
    FC + "Structure": "structure",
    FC + "Condition": "condition",
    FC + "Muscle": "muscle",
    FC + "BodyRegion": "region",
    FC + "MovementPattern": "pattern",
    FC + "ExerciseFamily": "family",
    FC + "Equipment": "equipment",
    FC + "EquipmentFamily": "equipment",
    FC + "Exercise": "exercise",
}

# Cue lexicons (prefix match on tokens). Kept small and explicit so a reviewer can audit them.
SAFETY_CUES = (
    "injur",
    "pain",
    "hurt",
    "bother",
    "sore",
    "tweak",
    "cranky",
    "aggravat",
    "flare",
    "sprain",
    "strain",
    "rehab",
    "recovering",
    "achy",
    "aching",
    "twinge",
    "irritat",
    "niggl",
    "torn",
    "tear",
    "ruptur",
    "surgery",
    "postop",
)
CONSTRAINT_CUES = SAFETY_CUES + ("avoid", "careful", "protect", "bad", "easy", "spare", "watch")
EXCLUSION_CUES = (
    "no",
    "not",
    "without",
    "avoid",
    "skip",
    "exclude",
    "excluding",
    "except",
    "nothing",
    "dont",
    "never",
    "zero",
    "minus",
)
ONLY_CUES = ("only", "just")
HAVE_CUES = ("has", "have", "with", "got", "owns", "using")
MOVEMENT_WORDS = {
    "squat",
    "squats",
    "row",
    "rows",
    "extension",
    "extensions",
    "press",
    "presses",
    "raise",
    "raises",
    "fly",
    "flys",
    "flyes",
    "lunge",
    "lunges",
    "bridge",
    "bridges",
    "thrust",
    "thrusts",
    "curl",
    "curls",
    "stretch",
}
STOPWORDS = {
    "a",
    "an",
    "the",
    "her",
    "his",
    "their",
    "my",
    "some",
    "for",
    "of",
    "to",
    "in",
    "on",
    "and",
    "or",
    "that",
    "this",
    "with",
    "is",
    "be",
    "been",
    "she",
    "he",
    "they",
    "him",
    "them",
    "me",
    "it",
    "its",
    "s",
    "can",
    "do",
    "make",
    "give",
    "build",
    "workout",
    "session",
    "exercises",
    "exercise",
    "plan",
    "minutes",
    "min",
    "today",
    "please",
    "any",
    "around",
    "focus",
    "us",
}
ROLE_TYPES = {
    "constraint": {"structure", "condition"},
    "exclusion": {"family", "pattern", "equipment", "exercise", "region"},
    "equipment": {"equipment"},
    "target": {"muscle", "region", "pattern", "family", "exercise", "structure", "equipment"},
}
FUZZY_MIN = 88
EMBED_TYPES = {"muscle", "structure"}  # see embed.py for why the embedding pass is this narrow


@dataclass
class Mention:
    text: str
    concept: str | None  # IRI, None if unresolved
    ctype: str | None
    role: str  # target | constraint | exclusion | equipment
    pass_: str  # exact | fuzzy | embedding | unresolved
    confidence: float
    extractor: str  # rules | llm | rules+llm
    side: str | None = None
    quantity: int | None = None
    clause: str = ""


@dataclass
class Resolution:
    prompt: str
    mentions: list[Mention] = field(default_factory=list)
    time_min: int | None = None
    equipment_only: bool = False
    blocking: list[str] = field(default_factory=list)  # fail-closed questions for the coach
    suggestions: dict[str, tuple[float, list[str]]] = field(default_factory=dict)  # safety word -> (score, guesses)
    notes: list[str] = field(default_factory=list)  # fail-open notes
    known_injuries: list[Injury] = field(default_factory=list)

    def of(self, role: str, *ctypes: str) -> list[Mention]:
        return [m for m in self.mentions if m.role == role and m.concept and (not ctypes or m.ctype in ctypes)]


def _norm_tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower().replace("'", "").replace("’", ""))


def _has_cue(tokens: list[str], cues: tuple[str, ...]) -> bool:
    return any(t.startswith(c) if len(c) > 3 else t == c for t in tokens for c in cues)


class Resolver:
    def __init__(self, g: DomainGraph):
        self.g = g
        self.labels: list[tuple[tuple[str, ...], str, str, str]] = []  # (tokens, iri, type, label kind)
        q = """SELECT ?c ?t ?l ?k WHERE { ?c a ?t . VALUES ?k { skos:prefLabel skos:altLabel skos:hiddenLabel } ?c ?k ?l }"""
        for r in g.query(q):
            t = TYPES.get(r["t"].value)
            if t:
                self.labels.append((tuple(_norm_tokens(r["l"].value)), r["c"].value, t, local(r["k"].value)))
        self.affects = {r["c"].value: r["s"].value for r in g.query("SELECT ?c ?s WHERE { ?c fc:affects ?s }")}
        self.pref = {iri: " ".join(lt) for lt, iri, _, k in self.labels if k == "prefLabel"}
        self.stems = {lt[0] for lt, _, t, _ in self.labels if len(lt) == 1 and len(lt[0]) >= 3}
        self.index = embed.LabelIndex([(" ".join(lt), iri, t) for lt, iri, t, _ in self.labels if lt])

    # -- matching passes ------------------------------------------------------
    def _exact(self, toks: tuple[str, ...], allowed: set[str]) -> tuple[str, str] | None:
        hits = [(iri, t) for lt, iri, t, _ in self.labels if lt == toks and t in allowed]
        if not hits:
            return None
        # Prefer the type most specific to the role (structure beats muscle for "lower back" as a constraint, etc.)
        order = ["condition", "structure", "family", "equipment", "region", "muscle", "pattern", "exercise"]
        return min(hits, key=lambda h: order.index(h[1]))

    def _fuzzy(self, text: str, allowed: set[str]) -> tuple[str, str, float] | None:
        best = None
        for lt, iri, t, _ in self.labels:
            if t not in allowed or not lt:
                continue
            score = fuzz.ratio(text, " ".join(lt))
            if score >= FUZZY_MIN and (best is None or score > best[2]):
                best = (iri, t, score)
        return best

    # -- the rules extractor + matcher ----------------------------------------
    def resolve(
        self, prompt: str, known_injuries: list[Injury] | None = None, llm_mentions: list[dict] | None = None
    ) -> Resolution:
        res = Resolution(prompt=prompt, known_injuries=list(known_injuries or []))
        res.time_min = _time_window(prompt)
        clauses = [c for c in re.split(r"[.;,!?\n]|\bbut\b", prompt) if c.strip()]
        risky = [s for s in re.split(r"[.;!?\n]", prompt) if _has_cue(_norm_tokens(s), SAFETY_CUES)]
        for clause in clauses:
            self._resolve_clause(clause, res, safety_context=any(clause.strip() in s for s in risky))
        if llm_mentions:
            self._union_llm(llm_mentions, res)
        self._fail_closed_checks(prompt, res)
        return res

    def _resolve_clause(self, clause: str, res: Resolution, safety_context: bool = False) -> None:
        toks = _norm_tokens(clause)
        used = [False] * len(toks)
        only = _has_cue(toks, ONLY_CUES)
        if only:
            res.equipment_only = True
        found: list[Mention] = []
        for n in (4, 3, 2, 1):  # longest match first
            for i in range(len(toks) - n + 1):
                if any(used[i : i + n]):
                    continue
                span = tuple(toks[i : i + n])
                hit = self._exact(span, set(TYPES.values()))
                if not hit:
                    continue
                iri, t = hit
                nxt = toks[i + n] if i + n < len(toks) else ""
                if t == "structure" and nxt in MOVEMENT_WORDS:
                    continue  # "back squat" names an exercise, not the back (SPEC_REVIEW 1.3)
                role = self._role(t, toks[max(0, i - 6) : i], toks[i + n : i + n + 4], only)
                if role not in ROLE_TYPES or t not in ROLE_TYPES[role]:
                    retyped = self._exact(span, ROLE_TYPES.get(role, set()))
                    if not retyped:
                        continue
                    iri, t = retyped
                for k in range(i, i + n):
                    used[k] = True
                found.append(
                    Mention(
                        " ".join(span),
                        iri,
                        t,
                        role,
                        "exact",
                        1.0,
                        "rules",
                        side=_side(toks, i),
                        quantity=_quantity(toks, i) if t == "equipment" else None,
                        clause=clause.strip(),
                    )
                )
        # fuzzy pass over leftover content words, restricted by the role their context implies
        for i, tok in enumerate(toks):
            if used[i] or tok in STOPWORDS or len(tok) < 4 or _is_cue(tok):
                continue
            if i + 1 < len(toks) and toks[i + 1] in MOVEMENT_WORDS:
                continue  # part of an exercise name ("back squat"), not a body area
            role = self._role(None, toks[max(0, i - 6) : i], toks[i + 1 : i + 5], only)
            hit = self._fuzzy(tok, ROLE_TYPES.get(role, ROLE_TYPES["target"]))
            if hit:
                used[i] = True
                found.append(
                    Mention(tok, hit[0], hit[1], role, "fuzzy", hit[2] / 100, "rules", side=_side(toks, i), clause=clause.strip())
                )
        # embedding pass: body-part slang only; a constraint is never resolved this way, only suggested
        for i, tok in enumerate(toks):
            if used[i] or tok in STOPWORDS or len(tok) < 3 or _is_cue(tok) or tok.isdigit():
                continue
            if i + 1 < len(toks) and toks[i + 1] in MOVEMENT_WORDS:
                continue
            if any(tok.startswith(st) and tok != st for st in self.stems):
                continue  # "kneeling" extends "knee": a posture word, not the body part (SPEC_REVIEW 1.3)
            role = self._role(None, toks[max(0, i - 6) : i], toks[i + 1 : i + 5], only)
            if role == "constraint" or safety_context:  # a pain/injury sentence: never guess, only ask
                if sug := self.index.suggest(tok, {"structure", "condition", "muscle"}):
                    res.suggestions[tok] = (sug[0], [self.pref.get(g, local(g)) for g in sug[1]])
                continue
            if role == "target" and (hit := self.index.match(tok, EMBED_TYPES)):
                used[i] = True
                found.append(Mention(tok, hit[0], hit[1], role, "embedding", hit[2], "rules", clause=clause.strip()))
        res.mentions.extend(found)

    def _role(self, ctype: str | None, before: list[str], after: list[str], only: bool) -> str:
        if ctype in ("structure", "condition", None) and (_has_cue(before, CONSTRAINT_CUES) or _has_cue(after, SAFETY_CUES)):
            return "constraint"
        if ctype == "condition":
            return "constraint"  # naming a diagnosis is always a safety constraint
        if _has_cue(before, EXCLUSION_CUES):
            return "exclusion"
        if ctype == "equipment" and (only or _has_cue(before, HAVE_CUES)):
            return "equipment"
        if ctype == "equipment":
            return "equipment"
        return "target"

    def _union_llm(self, llm_mentions: list[dict], res: Resolution) -> None:
        """Merge LLM-proposed mentions. The LLM can add caution, never remove it."""
        role_of = {
            "avoid": "constraint",
            "constraint": "constraint",
            "injury": "constraint",
            "exclude": "exclusion",
            "exclusion": "exclusion",
            "equipment": "equipment",
            "target": "target",
        }
        for lm in llm_mentions:
            role = role_of.get(lm.get("role", "target"), "target")
            if lm.get("negated") and role == "target":
                role = "exclusion"
            toks = tuple(_norm_tokens(lm.get("text", "")))
            hit = self._exact(toks, ROLE_TYPES.get(role, set())) if toks else None
            if not hit and toks:  # "his knee is bothering him": scan n-grams inside the mention, longest first
                spans = [toks[i : i + n] for n in (4, 3, 2, 1) for i in range(len(toks) - n + 1)]
                hit = next((h for sp in spans if (h := self._exact(sp, ROLE_TYPES.get(role, set())))), None)
            mtype = "exact"
            if not hit and toks:
                f = self._fuzzy(" ".join(toks), ROLE_TYPES.get(role, set()))
                hit, mtype = ((f[0], f[1]), "fuzzy") if f else (None, "unresolved")
            existing = next((m for m in res.mentions if hit and m.concept == hit[0]), None)
            if existing:
                existing.extractor = "rules+llm"
                if role == "constraint" and existing.role != "constraint" and existing.ctype in ("structure", "condition"):
                    existing.role = "constraint"
                    res.notes.append(f"'{existing.text}' treated as a constraint: extractors disagreed on polarity")
                elif role == "exclusion" and existing.role == "target":
                    existing.role = "exclusion"
                    res.notes.append(f"'{existing.text}' treated as an exclusion: extractors disagreed on polarity")
            elif hit:
                res.mentions.append(Mention(" ".join(toks), hit[0], hit[1], role, mtype, 0.9, "llm"))
            elif role == "constraint":
                content = [t for t in toks if t not in STOPWORDS and not _is_cue(t) and not t.isdigit()]
                spans = [toks[i : i + n] for n in (4, 3, 2, 1) for i in range(len(toks) - n + 1)]
                known = next((h for sp in spans if (h := self._exact(sp, set(TYPES.values())))), None)
                if known and known[1] not in ("structure", "condition", "muscle"):
                    res.notes.append(
                        f"LLM marked '{lm.get('text', '')}' as a constraint, but it names a {known[1]}, not a body area"
                    )
                elif content:  # a body area we cannot resolve: fail closed
                    res.mentions.append(Mention(lm.get("text", ""), None, None, "constraint", "unresolved", 0.0, "llm"))
                else:  # only symptom/cue words ("bothering"); the body area is resolved elsewhere or caught by the cue check
                    res.notes.append(f"LLM symptom mention '{lm.get('text', '')}' has no body area of its own")

    def _fail_closed_checks(self, prompt: str, res: Resolution) -> None:
        # Checked per sentence: "her hammy is off, sore since Saturday" is one concern across a comma.
        for sentence in (s.strip() for s in re.split(r"[.;!?\n]", prompt) if s.strip()):
            if not _has_cue(_norm_tokens(sentence), SAFETY_CUES):
                continue
            if not any(m.role == "constraint" and m.concept and m.clause and m.clause in sentence for m in res.mentions):
                words = _norm_tokens(sentence)
                cands = [v for t, v in res.suggestions.items() if t in words]
                guess = max(cands)[1] if cands else None  # the most body-like word in the sentence
                hint = f" Did you mean the {' or the '.join(guess)}?" if guess else ""
                res.blocking.append(f'Couldn\'t resolve the safety concern in "{sentence}". Which body area is affected?{hint}')
        for m in res.mentions:
            if m.role == "constraint" and not m.concept:
                res.blocking.append(f'Couldn\'t resolve "{m.text}". Please confirm the body area before I build a plan.')
        for m in res.mentions:
            if m.role == "constraint" and m.ctype == "muscle":
                res.blocking.append(f'"{m.text}" sounds like a soreness or injury concern. Which joint or area should I protect?')

    # -- to filter constraints ------------------------------------------------
    def constraints(self, res: Resolution, profile_equipment: list[str] | None = None) -> tuple[Constraints, list[str]]:
        """Build safety-filter constraints. Returns (constraints, trace notes)."""
        notes: list[str] = []
        known = res.known_injuries
        injuries: dict[str, Injury] = {i.id: i for i in known if i.status != "cleared"}
        for m in res.of("constraint", "structure", "condition"):
            structure = self.affects.get(m.concept, m.concept) if m.ctype == "condition" else m.concept
            s_local = structure.removeprefix(FCA)
            match = next((i for i in known if _related(self.g, i.structure, s_local)), None)
            if match:
                notes.append(f"'{m.text}' matched the member's recorded injury: {match.label} ({match.status})")
                continue
            cond = m.concept.removeprefix(FCC) if m.ctype == "condition" else "unspecified-complaint"
            iid = f"complaint-{s_local}"
            injuries[iid] = Injury(
                id=iid,
                label=f"{local(structure).replace('-', ' ')} (coach-reported)",
                structure=s_local,
                status="acute",
                condition=cond,
                side=m.side,
            )
            notes.append(f"'{m.text}' is new: treated as acute until confirmed (fail closed)")
        equipment = None
        excluded_equipment = {local(m.concept) for m in res.of("exclusion", "equipment")}
        stated = [local(m.concept) for m in res.of("equipment", "equipment")]
        if stated and res.equipment_only:
            equipment = stated
            notes.append("coach statement lists the full equipment for this plan (overrides profile for this plan only)")
        elif profile_equipment is not None:
            equipment = list(profile_equipment) + stated
        qty = {local(m.concept): m.quantity for m in res.of("equipment", "equipment") if m.quantity}
        c = Constraints(
            injuries=list(injuries.values()),
            equipment=equipment,
            equipment_quantity=qty,
            excluded_families={local(m.concept) for m in res.of("exclusion", "family")},
            excluded_patterns={local(m.concept) for m in res.of("exclusion", "pattern")},
            excluded_equipment=excluded_equipment,
        )
        return c, notes


def _related(g: DomainGraph, a: str, b: str) -> bool:
    q = f"ASK {{ {{ <{FCA + a}> fc:partOf* <{FCA + b}> }} UNION {{ <{FCA + b}> fc:partOf* <{FCA + a}> }} }}"
    return bool(g.query(q))


def _is_cue(tok: str) -> bool:
    return _has_cue([tok], CONSTRAINT_CUES + EXCLUSION_CUES + ONLY_CUES + HAVE_CUES)


def _side(toks: list[str], i: int) -> str | None:
    window = toks[max(0, i - 2) : i]
    return "left" if "left" in window else "right" if "right" in window else None


def _quantity(toks: list[str], i: int) -> int | None:
    before = toks[max(0, i - 2) : i]
    if any(w in before for w in ("a", "an", "one", "single", "1")):
        return 1
    if any(w in before for w in ("two", "2", "pair", "couple")):
        return 2
    return None


def _time_window(text: str) -> int | None:
    t = text.lower()
    m = re.search(r"(\d{1,3})\s*-?\s*(?:min|mins|minute|minutes)\b", t)
    if m:
        return int(m.group(1))
    if re.search(r"\bhalf\s+(an\s+)?hour\b", t):
        return 30
    if re.search(r"\b(an|one)\s+hour\b", t):
        return 60
    return None
