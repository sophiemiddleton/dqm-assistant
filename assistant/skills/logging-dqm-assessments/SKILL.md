---
name: logging-dqm-assessments
description: Record Mu2e DQM run assessments in agentlog, and read earlier ones back. Use when assessing a run with dqm-assistant (assess_run), when chasing a DQM alarm, when asked "has anyone looked at run X?", "what did we conclude about run X?", or when the user corrects or disputes a DQM verdict. Covers checking agentlog before an assessment, filing the conclusion as a report, and filing corrections.
metadata:
  version: "0.1.0"
  servers: "dqm-assistant, agentlog"
---

# Logging DQM assessments in agentlog

`dqm-assistant` works out what is wrong with a run. `agentlog` keeps what was concluded,
permanently and readable by everyone. This skill is the glue: read agentlog before assessing,
file the conclusion after, and file corrections as new reports. How to read a dqm-assistant
report (verdicts, classes) is in the `mu2e-dqm` skill; this one does not repeat it.

**Freedom level: low for filing.** An agentlog report can never be edited or deleted and is
readable by everyone. Follow the steps and the template; do not improvise the subjects.

## 1. Before assessing: read what is already known

1. `agentlog.list_reports(run=<run>, ref="system:<subsystem>")` (subsystem lower-case, e.g. `crv`).
2. If there are reports, `get_report(<id>)` on the most recent one or two. Check
   `corrected_by` and the `incoming_links`: a `supersedes` link means someone corrected it.
3. Tell the user what was already concluded, by whom (`author`) and when, before the new
   assessment. **A human correction (`supersedes`, `triggered_by: human`) outranks
   dqm-assistant's classification** for the same issue: say so if they disagree.

**Always still call `assess_run`** (step 2), even when a report exists: an agentlog report is
context, not a substitute. Skip it only if the user asked nothing but what was concluded
before. Runs get reprocessed, references change, and a filed report can be wrong.

## 2. Assess

Follow the `mu2e-dqm` skill: `dqm-assistant.assess_run(run)`, then any drill-down.

## 3. Decide whether to file

| Situation | File? |
|---|---|
| Woken by an alarm or a schedule (`triggered_by: alarm` / `schedule`) | Yes, always, including `GOOD` |
| A user asked about the run, and the session is interactive | **Ask first**: show title, severity, subjects and a short body summary, ask "File this permanently in agentlog?", and file only on an explicit yes to that question |
| The user says "make a report", "write a report" or "summarise" | **No.** That is an answer or hep-genesis's session report, not agentlog. Offer agentlog only if it fits, and ask as above |
| Only drill-down (`get_findings`, `history`, `compare`) on a run already reported in this session | No; add it to the report you file, or as a `followup_of` (step 5) |
| The new assessment says the same as the latest report, nothing new found | No; tell the user the earlier report still stands |
| `assess_run` failed or returned nothing | No report about the run. If the *tool* is broken, a report with subject `mcp:dqm-assistant.assess_run` is legitimate |

## 4. File the report

`agentlog.file_report` with these arguments:

| Argument | Value |
|---|---|
| `title` | `<SUBSYSTEM> run <run>: <VERDICT>` plus the main issue, e.g. `CRV run 125846: BAD, sector 2 digi rate drop (new)` |
| `summary` | The verdict and one line per real issue group (2–4 lines) |
| `severity` | from the table below |
| `triggered_by` | `alarm`, `schedule`, `human` (a user asked) or `agent` |
| `agent` | `dqm-assistant` |
| `subjects` | **one entry per line** (never comma-separated, see below) |
| `mentions` | items from groups that are *not* real issues (`expected`, `method_artefact`), and `ecl:<id>` entries you consulted |
| `tags` | `dqm,dqm-assistant,<verdict lower-case>` |
| `attrs` | JSON, see below |
| `body` | the template below |

**Severity** (never `critical` on your own; that means "someone must act now" and is a human's
or the alarm system's call):

| dqm-assistant result | severity |
|---|---|
| `GOOD` | `info` |
| `NEEDS-EXPERT` (any reason), or only `reference_artefact` groups | `warning` |
| `BAD` | `error` |

**Subjects**, one per line:

```
run:<run>
system:<subsystem lower-case>
metric:<group>/<subgroup>/<name>        one per item in a new/persistent group, at most 10
alarm:<group>/<subgroup>/<name>@<algo>  only for items flagged by a dqm_alarms method (e.g. @tranad, @limits)
```

dqm-assistant names items `group,subgroup,name` with commas. **Replace the commas with `/`**
for `metric:` and `alarm:`, and keep the case (`namex` is camelCase). A comma left in would
split the item into several bogus subjects, and agentlog cannot repair a subject once filed.
Items like `CRV (global)` are not metrics: leave them out of the subjects.

**attrs** (what a digest would parse rather than read):

```json
{"verdict": "BAD", "subsystem": "CRV",
 "groups": [{"name": "...", "cls": "new", "confidence": "high", "onset_run": 125840,
             "methods_bad": ["tranad"], "methods_good": ["ks"]}],
 "methods_judged": ["ks", "tranad"], "methods_not_judged": [],
 "assessment_created": "<report.created>"}
```

**Body template** (Markdown):

```markdown
## Verdict: <VERDICT>
<report.summary, in your words if it reads badly; one paragraph>

## Issues
- **<group name>** — <cls>, <confidence> confidence. Flagged by <methods_bad>; passed <methods_good>.
  Onset: run <onset_run> (<"at or before" if onset_is_lower_bound>). <one line of evidence>
- ...

## Not checked
- <each not_checked line, verbatim>
Methods that did not judge this run: <methods_not_judged, or "none">

## How this was checked
dqm-assistant `assess_run` (<refresh or cached>)<, then the drill-down calls and what they showed>.
<ecl entries or run-type context you used>
<Earlier agentlog reports on this run and whether this agrees: "agrees with #418" / "differs from #418 because ...">

## Recommendation
<what a human should do; never a good-run flag decision, only a recommendation>
```

Leave out sections that have nothing in them, except **Not checked**: write "nothing" there
rather than dropping it, because a missing method is the most common reason a verdict is weak.

After filing, give the user the returned `report_id`.

## 5. Corrections and follow-ups

Never file a fresh report to "replace" an old one. Use `agentlog.comment_on_report`:

| Situation | `relation` | `triggered_by` |
|---|---|---|
| The user says a class or verdict is wrong (e.g. "that is an LED run, it is expected") | `supersedes` | `human` |
| A re-assessment after reprocessing or a new reference changes the conclusion | `supersedes` | `agent` |
| You looked further (history, compare, ecl) and have more to add, same conclusion | `followup_of` | as appropriate |
| A remark that does not change the conclusion | `comments_on` | as appropriate |

Keep `inherit_subjects` at its default (true) so the correction is found under the same run.
In the body, say what the earlier report concluded, what is different now, and why. Check
with the user before filing a `supersedes` on their behalf.

## Never

- File without the user's yes in an interactive session; a report is permanent and public.
- Put raw tool output, tokens, or anything private in the body; summarise it.
- Put tool names in `subjects` (`mcp:` only when the report is *about* that tool).
- State causes, channels or numbers that are not in the dqm-assistant report or findings.
- Mark a run good or bad for physics; recommend, a human decides.
