# dqm-assistant

A method-agnostic DQM run assessor behind MCP. An orchestrator (HEP Genesis, Claude, ...)
asks "what's going on with run X?"; this service runs whatever detectors are configured,
groups and classifies their findings, and returns one report. Design: [DESIGN.md](DESIGN.md);
histogram access and references: [PLAN_hists_refs.md](PLAN_hists_refs.md).

```
dqm_assistant/
  findings.py      Finding, MethodCard, Group, RunReport  -- the only L1 -> L2 interface
  detectors/       L1 plugins: base.py (contract + registry)
                     ks.py          dqm.hist.compare against the reference
                     remote.py      any method emitting dqm-method-scores/1 (command, http or file)
                     tranad.py      remote + TranAD's card; scoring lives in ../tranad-score
                     dqm_alarms.py  anything already in the DQM driver (crv_ml/TranAD, limits)
                     vision.py      Mu2e-VisionDQM reviewer (needs LITELLM_API_KEY)
  histsource.py    run -> dqm.files -> /pnfs path -> summed run histograms (cached)
  references.py    YAML reference registry; only `approved` entries are used
  context.py       RunContext: run type, period, reference, histogram access
  assessor.py      L2: gather -> group -> classify -> corroborate -> (LLM) -> report
  llm.py           LiteLLM gateway client for the L2 LLM pass (optional)
  store.py         findings + reports per run, JSON
  service.py       config wiring; the bodies of the MCP tools
  server.py        the MCP server (stdio or streamable-http)
skills/mu2e-dqm.md the Genesis skill: how an orchestrator should use these tools
skills/logging-dqm-assessments/  Genesis skill: read and file assessments in agentlog (aitools mcp/agentlog)
references.yaml    the registry (124228 is a *candidate* until a CRV expert approves it)
```

## Run

```bash
../install.sh --tranad                         # once: the venv in ../.venv (see ../README.md)
cp config.example.yaml /exp/mu2e/data/users/$USER/dqm-assistant/config.yaml   # adjust paths
PY=../.venv/bin/python
CFG=/exp/mu2e/data/users/$USER/dqm-assistant/config.yaml

$PY -m pytest -q tests                                             # offline: fake detectors
$PY -m dqm_assistant --config $CFG --no-llm replay 124189 124537 125846
./start-stdio.sh                                                   # stdio, for hep-genesis
$PY -m dqm_assistant.server --config $CFG --http --port 8010       # HTTP, next to the other servers
```

### In hep-genesis (Mu2e aitools harness)

The harness is `aitools/harness/hep-genesis` (github.com/Mu2e/aitools). Install it per its
README; without node >= 20, `install.sh <dest> --no-ui` gives the CLI and automations. Then
add one entry to `/exp/mu2e/data/users/$USER/hep-genesis-data/servers.json` (or Servers ->
Add server in the web UI):

```json
{"name": "dqm-assistant", "transport": "stdio",
 "command": "/abs/path/dqm-assistant/assistant/start-stdio.sh"}
```

`start-stdio.sh` runs the server in the venv from `install.sh` (`$DQM_ASSISTANT_VENV`, default
`../.venv`), and reads
`/exp/mu2e/data/users/$USER/dqm-assistant/config.yaml` (or `$DQM_ASSISTANT_CONFIG`). The skill
(`skills/mu2e-dqm.md`, frontmatter dropped) is sent as the server's MCP instructions, so no
harness-side context file is needed. Replay recent runs first (`... replay <runs>`), or every
group comes out `new` for lack of history.

```bash
. /exp/mu2e/app/users/$USER/hep-genesis/current/env.sh
hep-genesis-agent --quick --project dqm-assistant --only-servers dqm-assistant,dqm,runs \
    --tool-timeout 600 --no-report "What is going on with run 125846?"
```

Always pass `--project`: without it a quick chat writes to `~/hep-genesis` (home quota),
whatever `HEP_PROJECTS_DIR` says.

For the browser UI (tmux, ssh tunnel, token), see [../WEB_UI.md](../WEB_UI.md).

## Adding a method

```python
@register("my_method")
class MyDetector(Detector):
    card = MethodCard(name="my_method", compares="...", granularity="histogram",
                      needs_reference=True, false_alarms=("...",))
    def assess(self, ctx): return [Finding(...), ...]
```

then `- {type: my_method}` under the subsystem's `detectors:`. Nothing else changes.

A method that runs **outside** this env (its own dependencies, a service, a batch job) needs no
Python here at all. Have it emit [dqm-method-scores/1](../method-scores/SCHEMA.md) and
configure the generic `remote` detector with a card and one transport:

```yaml
- type: remote
  method: my_method
  card: {compares: "...", granularity: metric, needs_reference: false, false_alarms: ["..."]}
  command: [/path/env/bin/python, -m, my_method, --sid, "{sid}", "{run}"]   # or url: / path:
```

## Status (2026-11-18)

Skeleton. 12 offline tests pass. Real-data smoke test: KS + DQM alarms on 006-001 runs
124189, 124537, 125846 against 124228 (approved in a scratch registry for the test only):
the run -> files -> /pnfs -> summed histogram path works (about 1 minute for 3 runs, cached
after). KS fails PEr, logchi2, crvDigisPerChannel and h1_peakAdc for all three (p = 0 at these
statistics), so every run is BAD/persistent; no DQM alarms exist for sid 118. That is the
expected KS behaviour, and it shows the gap below.

Known gaps:
- Corroboration needs two methods on the *same* item. TranAD and limits judge metrics, KS
  judges histograms, so they never confirm or contradict each other. The vision detector (or
  HYDRA) on the same histograms is what turns "KS alone" into method_artefact.
- KS gives no locus, so a dead block cannot be grouped by channel range. A per-half-block
  rate detector (as used to check the vision verdicts) would supply one.
- Run type is a config default until the runs MCP (token needed) is wired in.

### KS + TranAD test (2026-11-18)

TranAD was retrained on 006-001 (sid 118; 9 metrics with full coverage, exported with
dqm.reader to the pipeline's CSV format because the pipeline's MCP fetch fails for this
source). Replay of 122834, 124189, 124193, 124537, 125846:

| run | KS (6 histograms) | TranAD |
|---|---|---|
| 122834 | not checked (outside reference validity) | outlier in 27/28 subruns; drift 15/28 |
| 124189 | 4 BAD | drift 15/92 |
| 124193 | 5 BAD | outlier in its one subrun |
| 124537 | 4 BAD | GOOD |
| 125846 | 4 BAD | GOOD (misses the dead channel blocks) |

Headless Claude, asked about 122834 and 125846, read both reports and pulled TranAD's
findings to report that KS and TranAD disagree on 125846. The rules do not see that
disagreement: KS judges histograms, TranAD judges metrics, so no item is shared.
