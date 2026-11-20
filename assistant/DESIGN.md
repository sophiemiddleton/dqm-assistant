# dqm-assistant: a method-agnostic DQM service for agents

Status: design draft, 2026-11-18. Nothing is implemented yet.

## Question

An orchestrator agent (HEP Genesis, Claude, anything that speaks MCP) asks
"what's going on with run X?". What answers, and how, without committing to one
anomaly-detection method (KS, limits, TranAD, a vision LLM, a CNN, ...)?

## Where things sit

```
 Genesis (orchestrator, open-ended reasoning, talks to the shifter/expert)
   |  MCP
   +-- dqm-assistant   <- this service (new)
   |     L2 run assessor : fixed LLM pipeline -> run report
   |     L1 detectors    : plugins, no LLM required (except a vision detector)
   |     store           : findings + reports per run, computed on run arrival
   +-- dqm      (existing: metrics, limits)        mu2eaigpvm01:8001
   +-- runs     (existing: run type, config, flags) :8006
   +-- ecl      (existing: shift logbook)           :8005
   +-- kb       (existing: DocDB)                   :8008
   +-- metacat  (existing: file lookup)             :8002
```

Genesis core stays untouched: it is deliberately domain-neutral. Mu2e enters
through (a) this MCP server and (b) a Genesis skill file (`skills/mu2e-dqm.md`)
that holds the triage recipe below.

## L1: the detector contract (the agnostic part)

Every method is a plugin implementing one interface:

```python
class Detector:
    card: MethodCard            # static description, see below
    def assess(self, run: RunRef, items: list[ItemRef],
               reference: Reference | None) -> list[Finding]: ...
```

`Finding` is the only thing the rest of the system sees:

| field | meaning |
|---|---|
| `run`, `subrun` | what was assessed (subrun optional) |
| `subsystem`, `item` | e.g. `CRV`, `crvDigisPerChannel` or a metric name |
| `method`, `method_version` | e.g. `ks@dqm.hist.compare`, `tranad@crv-tranad-v2` |
| `score`, `threshold`, `flag` | raw number, the cut it was compared with, GOOD/BAD/UNSURE |
| `reference` | reference id + version used (or `history:last-N` for time-series methods) |
| `evidence` | paths/URLs: plot, overlay, per-input contributions, LLM text |
| `locus` | optional finer location: channel range, FEB, ROC, bin range |

`MethodCard` is what lets the agent weigh a method it has never seen:
what it compares (shape vs reference, metric vs limits, time series vs
history), granularity, known blind spots and false-alarm modes, and
calibration status. Examples:

- KS: shape vs reference; oversensitive at high statistics (flags nearly
  everything at 006-001 statistics); blind to normalisation.
- Limits: metric vs hand-set band; only as good as the band; already alarming
  nightly.
- TranAD: multivariate metric history; misses faults when training spread is
  inflated by mixed configuration periods; threshold not label-calibrated.
- Vision LLM: shape vs reference with written instructions; inherits reference
  faults; non-deterministic; costs a model call per histogram.

Adding a method = one plugin + one card. Nothing downstream changes.

## L2: the run assessor (what "the agent" does, method-independent)

A fixed pipeline per run. LLM calls only where marked; everything else is
code, so the output is reproducible and auditable.

1. **Gather.** All findings for the run from every enabled detector.
2. **Context (code).** From `runs`: run type (LED, cosmics, beam, empty),
   configuration period, flags. From the reference registry: which reference
   applied and whether it is approved. From the store: the same items in the
   previous N runs.
3. **Group (code, then LLM).** Collapse findings that share a cause: same
   locus across several items (a dead half-block shows up in digi rates,
   PE and channel plots), same onset run across items (a configuration
   change). Code proposes groups by locus/onset; an LLM call names them.
4. **Classify each group (LLM, with rules first).**
   - *expected*: explained by run type or a known configuration change
     (LED run, empty run, new period)
   - *persistent*: present in earlier runs too; already known or never noticed
   - *new*: first seen in this run
   - *reference artefact*: present relative to this reference but not to an
     alternative one, i.e. the reference is at fault
   - *method artefact*: only one method flags it and its card lists that as a
     known false-alarm mode (e.g. KS alone at high statistics)
5. **Corroborate.** Agreement across methods raises confidence; disagreement
   is reported, not hidden. Optionally pull ECL entries for the run window and
   known-issue notes (kb) for the subsystem.
6. **Report (LLM).** One structured answer:
   - overall verdict GOOD / BAD / NEEDS-EXPERT, with confidence
   - list of issue groups: description, locus, onset run, class, which methods
     flagged it, evidence links
   - what was *not* checked (missing histograms, method not calibrated,
     reference unapproved)
   - suggested next step for a human (never sets a goodrun flag itself)

Results are computed when a run arrives (or on demand once, then cached),
because a full pass is minutes of model calls.

## MCP tools exposed

| tool | returns |
|---|---|
| `assess_run(run, subsystem=None, refresh=False)` | the L2 report (cached) |
| `get_findings(run, subsystem=None, method=None)` | raw L1 findings |
| `compare(run, item, reference=None, method=None)` | one ad-hoc detector call |
| `history(item, runs=..., method=None)` | score time series for an item |
| `list_flagged(since, subsystem=None, cls=None)` | runs with new/persistent issues |
| `list_methods()` | the method cards |
| `get_reference(subsystem, run)` | which reference applies, its status |

Return shape follows Genesis's ArtifactResult convention
(`{status, files, message, metadata}`) so plots render in its UI.

## What Genesis (L3) adds on top

Open-ended follow-ups the fixed pipeline does not cover: "since when?",
"compare with run Y", "is this the same thing we saw in October?", "draft an
ECL entry", writing a summary for the CRV group. The Mu2e skill file tells it
to start from `assess_run`, trust the grouping, and drill into `get_findings`
and `history` only when asked or when confidence is low.

## Inputs the service needs

Detailed plan: [PLAN_hists_refs.md](PLAN_hists_refs.md).


- **Histograms**: not available through the dqm MCP (metrics only). Read the
  ROOT files from disk on the gpvm, locating them via metacat. Ask DJ about a
  histogram endpoint in the Query Engine later.
- **References**: none exist in Mu2e/DQM today. Needs a registry keyed by
  (subsystem, run type, configuration period): reference run, file, validity
  range, approver, version. Start as versioned YAML here; move to a DQM table
  if DJ prefers. A reference is sanity-checked (e.g. dead-channel scan) before
  approval; the 124336 case showed what a flawed reference does.
- **Configuration periods**: from runs MCP / a periods file; needed both for
  reference choice and for the *expected* class.

## Open questions

1. Where references live and who approves them (CRV group + DJ).
2. Histogram access: disk now, Query Engine endpoint later?
3. Hosting on mu2eaigpvm01 next to the existing servers; gpvm load budget.
4. Is grouping-by-locus feasible generically, or does each subsystem need a
   locus map (channel -> FEB -> ROC)?
5. Evaluation: replay 006-001 (known faults: 125846 dead blocks, PE shoulder
   shift ~125700, flawed reference 124336) and check the reports.
