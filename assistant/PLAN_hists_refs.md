# Plan: histogram access and reference histograms

Status: plan, 2026-11-18. Companion to [DESIGN.md](DESIGN.md).

## Q1. How do we get the histograms: through the DQM MCP or from disk?

### Answer: both. The DQM database says *which* file; the bytes are read from disk.

What exists today (checked 2026-11-18):

| piece | status |
|---|---|
| `dqm.files` table: (sid, iid) -> Mu2e file name, "so an anomalous metric can be traced back to it" | **populated for sid 118** (`crvreco kpp_crv file 006-001`): 4228 rows, one per subrun file, up to run 125895. Empty for older sources (004-000, 005-001). |
| DQM MCP (mu2eaigpvm01:8001) | tools: sources, versions, values, intervals, metrics/limits, alarms, alarm causes. **No tool for `dqm.files`**, and no histogram content. |
| `dqm.catalog` (DJ's package) | metacat lookup + `file_url(name)`: Mu2e file name -> path via `mdh_names` hash. Needs the `mu2e-dqm[catalog]` extra (not in our env yet). Verified by hand: the name from `dqm.files` exists at the hashed path under `/pnfs/.../cosmics_crv/crvreco-006-001-file/root/cb/60/`. |
| `dqm.hist` (DJ's package) | uproot reader -> `hist.Hist`, accepts local, /pnfs and `root://` paths; KS / fraction comparison already ported from ROOT. |
| our `realdata.py` | globs the /pnfs dataset directory and sums subrun files per run. Works, but bypasses the database. |

Why not push histogram content through the DQM MCP: a run is tens to
hundreds of subrun files; one assessment touches ~10 histograms x ~20 runs.
That is file I/O, not an agent conversation. The service should read files
locally and only hand *results* (and small plots) to agents.

### Plan

**Phase 0 (now, no one else needed).** In dqm-assistant, a `histsource` module:

1. run -> intervals -> file names: query `dqm.files` via `dqm.reader.DqmReader`
   (Query Engine, read-only), joined with `dqm.intervals` for run/subrun.
2. file name -> path: `dqm.catalog.file_url` (install `mu2e-dqm[catalog]`).
   Fallback for sources with an empty `dqm.files` (004/005): the directory
   glob from `realdata.py`.
3. read with `dqm.hist.open_file`; sum subruns to one histogram per run
   (means for profile-type histograms, as `realdata.py` already does).
4. cache per (source, run, histogram) on local disk; the summed run file is
   the unit every detector sees. Record the list of subrun files used, so a
   late-arriving subrun invalidates the cache.

Result: the run -> file link is the *same* one the metrics use, so a metric
alarm and a histogram verdict point at the same files.

**Phase 1 (small ask to DJ).** Add a `list_files(sid, run range)` tool to the
DQM MCP that exposes the existing `dqm.files` table. Then an orchestrator can
answer "which files is this run?" without dqm-assistant, and our Phase 0 step 1
switches to it. No schema change; one read-only tool.

**Phase 2 (optional, later).** A `get_histogram(run, name, source)` tool
returning bin edges and contents as JSON, for an agent that wants to look at
the numbers itself. It belongs in dqm-assistant (which already has the summed,
cached run histograms) unless DJ wants it in the DQM MCP.

Checks before relying on it:
- every subrun on disk has a `dqm.files` row (compare against the glob for 006-001);
- what happens to `dqm.files` when a dataset is reprocessed (new version = new sid?).

## Q2. Do we have / plan reference histograms? How is that managed?

### Today: none.

Mu2e/DQM has no reference concept (only a "reference" overlay label in the
plotting code). The goodrun database (grlTool) held only test entries when
last checked (2026-11-06). Our studies picked references by hand
(124336, then 124228) and the first choice was flawed: it had dead
half-blocks, which made every run look BAD on the channel plot.

### The model: a reference is to histograms what `dqm.limits` is to metrics

`dqm.limits` gives an accepted range for (source, metric, interval). A
reference gives an accepted shape for (source, histogram, run range). Same
questions: who sets it, for which period, what version was in force.

Two kinds of reference, both recorded on every finding:

- **fixed**: a chosen good run (or the sum of a few good runs, to cut
  statistical noise in the reference itself), valid for a run range;
- **rolling**: "last N runs judged good", used by history-based methods
  (TranAD, drift). Recorded as `history:<N>@<run range>`.

### Registry entry

```yaml
- id: crv-cosmics-p3-v2
  source: {process: crvreco, stream: kpp_crv, version: 006-001}
  run_type: cosmics            # LED, cosmics, beam...
  period: p3                   # configuration period
  valid_runs: [125700, null]   # open-ended until superseded
  reference_runs: [124228]     # one or several, summed
  histograms: all              # or a list, when one histogram needs its own
  status: approved             # candidate | approved | retired
  approved_by: <name>, date: 2026-..
  checks: {dead_channels: pass, stats: pass}
  supersedes: crv-cosmics-p3-v1
  note: "124336 rejected: dead half-blocks 1664-1791 even, 1920-2047 odd"
```

### Plan

**Phase 0 (now).** Versioned YAML in the dqm-assistant repo (git history =
audit trail). Selection: run -> run type and configuration period (runs MCP
`get_run` / `get_config_blob`, or a periods file like
`configs/periods_005-001.csv` until that exists) -> the approved entry whose
`valid_runs` covers the run. No approved entry -> findings are marked
"no reference" and the report says so; nothing is silently compared against
a stale one.

**Phase 1. Candidate generation, human approval.** For each period the
service proposes 2-3 candidate reference runs, ranked by automatic checks:
- dead / hot channel scan per half-block (the check that caught 124336),
- enough statistics, normal run length, normal run type,
- closeness to the median shape of the period (a run typical of its neighbours),
- not flagged by any detector against the current reference.
An expert (CRV: Rob M, Ralf; DQM: DJ) approves one; status goes
candidate -> approved. If grlTool gets real entries, require the reference
to be on the good-run list.

**Phase 2. Change and invalidation.**
- A new configuration period (or a detector change) -> new candidates.
- A reference found flawed -> status `retired`, a new version, and every
  run assessed against it is re-assessed. Reports are keyed on the reference
  version, so old and new verdicts stay distinguishable.
- Drift guard: if most runs of a period start failing against the same
  reference (as with 124336), the service flags the *reference* for review
  instead of reporting N bad runs.

**Phase 3. Move into the DQM database (if DJ agrees).** A `references`
table parallel to `limits`, keyed by (sid, histogram, run range), plus a
`get_reference(sid, run)` tool on the DQM MCP, so other tools (the web
histogram tab overlay, the limits evaluator) can use the same references.

## Questions to settle with DJ

1. Can the DQM MCP expose `dqm.files` (a `list_files` tool)? Will `dqm.files`
   be filled for every new source, and backfilled for 004/005?
2. Does reprocessing make a new sid, and does `dqm.files` follow it?
3. References: YAML in our repo first, DQM table later. Agreed? Who approves
   for CRV?
4. What defines a configuration period: a runs-database field, or a list we
   keep?
5. Should the web app's histogram tab use the same registry for its overlay?
