"""L2: the run assessor. Six fixed steps; the LLM only names, reviews classes and writes.

Every step works without a model (rules + a template summary), so the service degrades to
"deterministic and terse" rather than failing when the gateway is down or no key is set.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple

from dqm_assistant.context import EXPECTED_RUN_TYPES, RunContext
from dqm_assistant.findings import (BAD, CLASSES, EXPECTED, GOOD, METHOD_ARTEFACT, NEW, PERSISTENT,
                                 REFERENCE_ARTEFACT, UNSURE, Finding, Group, MethodCard, RunReport)

LOG = logging.getLogger("dqm_assistant.assessor")

REFERENCE_SUSPECT_FRACTION = 0.8   # flagged in >= 80% of recent runs vs the same reference
MIN_HISTORY_FOR_REFERENCE = 5


# ---------------------------------------------------------------- step 1: gather
def gather(detectors: Sequence, ctx: RunContext) -> Tuple[List[Finding], List[str], List[str]]:
    """-> findings, not_checked notes, methods that actually judged the run."""
    findings, not_checked, checked = [], [], []
    for d in detectors:
        if d.card.needs_reference and ctx.reference is None:
            not_checked.append(f"{d.method_id}: no approved reference for this run")
            continue
        try:
            got = d.assess(ctx)
            findings += got
            if not got or any(f.flag != UNSURE for f in got):   # [] = ran, saw nothing
                checked.append(d.method_id)
        except Exception as exc:                      # one broken method must not sink the run
            LOG.exception("detector %s failed", d.method_id)
            not_checked.append(f"{d.method_id}: failed ({type(exc).__name__}: {exc})")
    unsure = [f for f in findings if f.flag == UNSURE]
    for f in unsure:
        not_checked.append(f"{f.method} on {f.item}: {f.evidence.get('note', 'unsure')}")
    return findings, not_checked, checked


# ---------------------------------------------------------------- step 3: group (code part)
def group(findings: Sequence[Finding]) -> List[Group]:
    """BAD findings that share a locus, or else an item, go together. The LLM may merge further."""
    bad: Dict[str, List[Finding]] = defaultdict(list)
    for f in findings:
        if f.flag == BAD:
            bad[f.locus or f.item].append(f)
    by_item_good: Dict[str, set] = defaultdict(set)
    for f in findings:
        if f.flag == GOOD:
            by_item_good[f.item].add(f.method)
    groups = []
    for key, fs in bad.items():
        g = Group(key=key, findings=fs)
        g.methods_bad = sorted({f.method for f in fs})
        g.methods_good = sorted(set().union(*(by_item_good[i] for i in g.items)) - set(g.methods_bad))
        groups.append(g)
    return groups


# ---------------------------------------------------------------- step 4: classify (rules)
def _flagged_in(history: Sequence[Tuple[int, List[Finding]]], g: Group,
                reference: Optional[str]) -> List[int]:
    items = set(g.items)
    runs = []
    for run, fs in history:
        if any(f.flag == BAD and f.item in items and (reference is None or f.reference == reference)
               for f in fs):
            runs.append(run)
    return runs


def _status_in(fs: Sequence[Finding], items: set) -> Optional[str]:
    """BAD / GOOD for the group's items in one earlier run, or None if no method judged them."""
    mine = [f for f in fs if f.item in items and f.flag in (BAD, GOOD)]
    if any(f.flag == BAD for f in mine):
        return BAD
    return GOOD if mine else None


def classify(g: Group, ctx: RunContext, history, cards: Dict[str, MethodCard]) -> None:
    flagged = _flagged_in(history, g, None)
    items = set(g.items)
    assessed = [(r, _status_in(fs, items)) for r, fs in history]
    assessed_runs = [r for r, st in assessed if st is not None]
    g.onset_run, g.onset_is_lower_bound = None, False
    if flagged:                                      # walk back the unbroken BAD streak
        onset, bounded = ctx.run, True               # bounded: ran out of judged runs
        for r, st in reversed(assessed):
            if st == BAD:
                onset = r
            elif st == GOOD:
                bounded = False                      # a judged GOOD run ends the streak
                break
            else:                                    # not judged in that run: onset unknown
                break
        g.onset_run = onset if onset != ctx.run else None
        g.onset_is_lower_bound = g.onset_run is not None and bounded

    ref_methods = [m for m in g.methods_bad if cards.get(m) and cards[m].needs_reference]
    same_ref = _flagged_in(history, g, ctx.reference_id) if ctx.reference_id else []
    single = len(g.methods_bad) == 1 and g.methods_good
    known_fa = single and cards.get(g.methods_bad[0]) and cards[g.methods_bad[0]].false_alarms

    if ctx.run_type in EXPECTED_RUN_TYPES:
        g.cls, g.reason = EXPECTED, f"run type is {ctx.run_type}"
    elif (ref_methods and len(history) >= MIN_HISTORY_FOR_REFERENCE
          and len(same_ref) >= REFERENCE_SUSPECT_FRACTION * len(history)):
        g.cls = REFERENCE_ARTEFACT
        g.reason = (f"flagged against {ctx.reference_id} in {len(same_ref)}/{len(history)} recent runs; "
                    "check the reference before the runs")
    elif known_fa:
        g.cls = METHOD_ARTEFACT
        g.reason = (f"only {g.methods_bad[0]} flags it ({', '.join(g.methods_good)} pass); "
                    f"known false alarm: {cards[g.methods_bad[0]].false_alarms[0]}")
    elif flagged:
        g.cls, g.reason = PERSISTENT, (f"also flagged in {len(flagged)}/{len(assessed_runs)} recent "
                                       f"runs where these items were assessed")
        if g.onset_is_lower_bound:
            g.reason += (f"; present since at least run {g.onset_run}; earlier runs were not "
                         "assessed for these items, so the true onset is unknown")
    else:
        g.cls, g.reason = NEW, "not flagged in recent runs"

    # ---- step 5: corroborate
    n_bad = len(g.methods_bad)
    calibrated = any(cards.get(m) and cards[m].calibrated for m in g.methods_bad)
    g.confidence = "high" if n_bad >= 2 or calibrated else ("low" if g.cls == METHOD_ARTEFACT else "medium")


# ---------------------------------------------------------------- verdict
def verdict(groups: Sequence[Group], not_checked: Sequence[str], checked: Sequence[str]) -> str:
    if not checked:
        return "NEEDS-EXPERT"                         # nothing judged the run: never call it GOOD
    real = [g for g in groups if g.cls in (NEW, PERSISTENT)]
    if any(g.cls == REFERENCE_ARTEFACT for g in groups):
        return "NEEDS-EXPERT"
    if real:
        return "BAD" if any(g.confidence != "low" for g in real) else "NEEDS-EXPERT"
    if not_checked and not groups:
        return "NEEDS-EXPERT" if any("no approved reference" in n for n in not_checked) else "GOOD"
    return "GOOD"


# ---------------------------------------------------------------- steps 3/4/6: LLM pass
SYSTEM = """You are the data-quality assessor for one Mu2e subsystem. You receive, for one run,
groups of anomaly findings already produced by several detection methods, each with a method card
saying what the method compares and how it is known to fail, plus run context and a rule-based
class for each group. Your job:
1. give each group a short name a shifter understands (what is wrong, where);
2. merge groups that clearly share one cause (same channels, same onset, same symptom);
3. keep or change each group's class, one of: new, persistent, reference_artefact,
   method_artefact, expected -- and say why in one sentence. Change it only with a reason
   the evidence supports;
4. write a 3-6 sentence summary for the shift crew and one concrete next step for a human.
Do not invent findings, numbers or causes that are not in the input. Say what was not checked.
Reply with JSON only:
{"groups":[{"keys":["<group key>",...],"name":"...","cls":"...","reason":"..."}],
 "summary":"...","next_step":"..."}"""


def llm_pass(llm, groups: List[Group], ctx: RunContext, cards: Dict[str, MethodCard],
             not_checked: List[str]) -> Tuple[List[Group], str, str]:
    payload = {
        "context": ctx.summary(),
        "method_cards": {m: c.to_dict() for m, c in cards.items()},
        "not_checked": not_checked,
        "groups": [{"key": g.key, "items": g.items, "rule_class": g.cls, "rule_reason": g.reason,
                    "methods_bad": g.methods_bad, "methods_good": g.methods_good,
                    "onset_run": g.onset_run, "onset_is_lower_bound": g.onset_is_lower_bound,
                    "confidence": g.confidence,
                    "evidence": [{"method": f.method, "item": f.item, "score": f.score,
                                  "subrun": f.subrun, "locus": f.locus,
                                  "evidence": {k: str(v)[:600] for k, v in f.evidence.items()}}
                                 for f in g.findings[:20]]}
                   for g in groups],
    }
    out = llm.json(SYSTEM, json.dumps(payload, default=str))
    by_key = {g.key: g for g in groups}
    merged: List[Group] = []
    used = set()
    for spec in out.get("groups", []):
        members = [by_key[k] for k in spec.get("keys", []) if k in by_key and k not in used]
        if not members:
            continue
        used.update(m.key for m in members)
        g = members[0]
        for m in members[1:]:                         # merge: union of evidence
            g.findings += m.findings
            g.methods_bad = sorted(set(g.methods_bad) | set(m.methods_bad))
            g.methods_good = sorted((set(g.methods_good) | set(m.methods_good)) - set(g.methods_bad))
        g.key = " + ".join(m.key for m in members)
        g.name = spec.get("name", g.key)
        if spec.get("cls") in CLASSES and spec["cls"] != g.cls:
            g.reason = f"{spec.get('reason', '')} (rules said {g.cls}: {g.reason})"
            g.cls = spec["cls"]
        merged.append(g)
    merged += [g for g in groups if g.key not in used and not any(g is m for m in merged)]
    return merged, out.get("summary", ""), out.get("next_step", "")


def template_summary(groups: Sequence[Group], v: str, ctx: RunContext) -> Tuple[str, str]:
    if not groups:
        if v != "GOOD":
            return f"Run {ctx.run}: no method could judge this run.", "Fix the inputs listed under not_checked."
        return f"Run {ctx.run}: no method flagged anything.", "None."
    lines = [f"Run {ctx.run} ({ctx.run_type}): {len(groups)} issue group(s), verdict {v}."]
    for g in groups:
        lines.append(f"- [{g.cls}] {g.name or g.key}: {', '.join(g.methods_bad)} BAD"
                     + (f", {', '.join(g.methods_good)} GOOD" if g.methods_good else "")
                     + f". {g.reason}.")
    step = ("Check the reference." if v == "NEEDS-EXPERT" and any(g.cls == REFERENCE_ARTEFACT for g in groups)
            else "Look at the new groups' evidence." if v != "GOOD" else "None.")
    return "\n".join(lines), step


# ---------------------------------------------------------------- the pipeline
def assess(ctx: RunContext, detectors: Sequence, history, llm=None) -> Tuple[RunReport, List[Finding]]:
    cards = {d.method_id: d.card for d in detectors}
    findings, not_checked, checked = gather(detectors, ctx)     # 1
    groups = group(findings)                                    # 3 (code)
    for g in groups:                                            # 2 (history) + 4 + 5
        classify(g, ctx, history, cards)
    summary = next_step = ""
    model = None
    if llm is not None and groups:                              # 3/4/6 (LLM)
        try:
            groups, summary, next_step = llm_pass(llm, groups, ctx, cards, not_checked)
            model = llm.model
        except Exception as exc:
            LOG.warning("LLM pass failed, using rules only: %s", exc)
            not_checked.append(f"LLM summary failed ({type(exc).__name__})")
    v = verdict(groups, not_checked, checked)
    if not summary:
        summary, next_step = template_summary(groups, v, ctx)
    report = RunReport(run=ctx.run, subsystem=ctx.subsystem, verdict=v, summary=summary,
                       groups=groups, context=ctx.summary(), not_checked=not_checked,
                       next_step=next_step, methods=sorted(cards),
                       created=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                       llm_model=model)
    return report, findings
