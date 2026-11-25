---
name: mu2e-dqm
description: Answer data-quality questions about Mu2e runs ("what's going on with run X?", "since when?", "is the reference OK?") using the dqm-assistant MCP server plus the dqm, runs and ecl servers.
---

# Mu2e data quality

Servers: `dqm-assistant` (run reports), `dqm` (raw metrics, limits, alarms), `runs` (run type,
configuration), `ecl` (shift logbook), `kb` (DocDB).

## Answering "what's going on with run X?"

1. `dqm-assistant.assess_run(run)`. Report the verdict, then each issue group: its name, class,
   which methods flagged it and which passed, onset run. Quote the report's `not_checked`.
2. Trust the grouping and classes unless the user disputes them. Do not re-run detectors to
   "double check" a high-confidence group.
3. Drill down only when asked or when a group's confidence is low:
   - `get_findings(run, method=...)` for raw scores and evidence;
   - `history(item, run_min, run_max)` for "since when?";
   - `compare(run, item, method=...)` for one fresh comparison.
   - On-demand methods (`list_methods` shows `on_demand: true`, e.g. `vision`) are not part of
     `assess_run`. Use one with `compare` when the user asks what exactly is wrong with a
     flagged histogram: vision answers in words (which channels, which FEBs) where the routine
     methods give only a flag and a score. It costs one LLM call per histogram, so call it for
     the flagged items only, and say that its answer is one more method's view, not a verdict
     on the run.
4. Context the report does not have: `ecl` entries in the run's time window; `runs.get_run`
   if the run type looks wrong.

## How to read the verdict

- `GOOD`: every configured method judged the run and nothing real was found.
- `BAD`: at least one real (`new` / `persistent`) issue with medium or high confidence.
- `NEEDS-EXPERT`: the run could not be cleared. Say which reason applies: a suspect reference,
  only low-confidence issues, or **a method that did not judge the run** (failed, no
  reference, no data). In that last case, name the method and quote its `not_checked` line.
  Never describe the run as fine. List methods from `methods_judged` and
  `methods_not_judged`, not from `methods` (that is only what is configured).

## How to read the classes

- `reference_artefact`: say the *reference* is suspect, not the run; suggest
  `get_reference(run)` and an expert check. Never call the run bad on this alone.
- `method_artefact`: one method in a known false-alarm mode (e.g. KS at high statistics);
  mention it, do not alarm on it.
- `expected`: explained by run type (LED, empty); one line.
- `new` / `persistent`: the real issues; for persistent, give the onset run.

## Never

- Set or suggest setting a good-run flag yourself: recommend, a human decides.
- Invent numbers, channels or causes not present in the report or findings.
- Compare against a reference that `get_reference` does not return.
