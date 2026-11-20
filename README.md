# dqm-assistant

An agentic interface to Mu2e data quality monitoring (DQM). You ask a question in plain
language ("what's going on with run 125846?") and an LLM agent answers it. The agent runs in
the Mu2e hep-genesis harness and uses this repository's MCP server, which runs the configured
anomaly methods (KS, TranAD, DQM alarms, ...), groups and classifies what they find, and
returns one report.

| Directory | What it is |
|---|---|
| [`assistant/`](assistant/README.md) | The **MCP server** (`dqm_assistant` package) that exposes the DQM assessment tools. It is the interpretation layer. |
| [`tranad-score/`](tranad-score/README.md) | A standalone "score this run" service for the TranAD anomaly model. The assistant uses it as a detector. |
| [`method-scores/`](method-scores/SCHEMA.md) | The output contract (`dqm-method-scores/1`) for any method that runs outside the assistant. |

## Requirements

- **The Python environment of CrossExperimentalAIDQM.** Its `envs/setup_ana_env.sh` sets up the
  Mu2e ana env, anldq/torch (for TranAD), Mu2e/DQM's `dqm` package and `dqm_pipeline`. Point
  `DQM_ASSISTANT_ENV` at it (default:
  `/exp/mu2e/app/users/$USER/CrossExperimentalAIDQM/envs/setup_ana_env.sh`). Without TranAD,
  any env with `mcp>=2`, `pyyaml` and `mu2e-dqm` runs the server and the KS and alarm detectors.
- **A harness**: hep-genesis from [Mu2e/aitools](https://github.com/Mu2e/aitools)
  (`harness/hep-genesis`). Setup and the `servers.json` entry are in
  [assistant/README.md](assistant/README.md#in-hep-genesis-mu2e-aitools-harness).
- **Per-user data** (config, trained models, cache, store) outside the repo, by default
  `/exp/mu2e/data/users/$USER/dqm-assistant/`. Start from
  [assistant/config.example.yaml](assistant/config.example.yaml).

```bash
source $DQM_ASSISTANT_ENV
cd assistant && PYTHONPATH=$PWD:$PYTHONPATH python -m pytest -q tests     # offline, 22 tests
```

## Layers

```
 User: "what's going on with run 125846?"
        │
 ┌──────▼──────────────────────────────┐
 │ HARNESS / ORCHESTRATOR              │  hep-genesis (aitools harness); Claude Code also tested
 │  - runs the LLM conversation loop   │
 │  - starts and connects MCP servers  │
 │  - loads skill files (instructions) │
 └──────┬──────────────────────────────┘
        │ MCP protocol (JSON over stdio)
 ┌──────▼──────────────────────────────┐
 │ dqm-assistant  (MCP server)         │  interpretation layer
 │  - groups findings, finds onset,    │
 │    classifies (expected/persistent/ │
 │    new/reference or method artefact)│
 │  - corroborates across methods      │
 │  - remembers past runs (store)      │
 └──────┬──────────────────────────────┘
        │ Python calls (detector plugins)
 ┌──────▼──────────────────────────────┐
 │ Detectors: ks, tranad (tranad-score)│  "is this run anomalous, by method X?"
 │ dqm_alarms (limits, crv_ml), vision │
 │ remote (any dqm-method-scores/1)    │
 └──────┬──────────────────────────────┘
        │
   Mu2e DQM database + histogram files on /pnfs
```

## Terms

**MCP (Model Context Protocol).** A standard way to expose tools to an LLM. An MCP server is an
ordinary program. It lists its tools with their arguments and descriptions, and answers each call
with JSON. It does no LLM reasoning itself. dqm-assistant is a Python MCP server. The harness
starts it as a subprocess and talks to it over stdin/stdout, so the server must never print
anything else to stdout.

**Harness.** The program that runs the agent. It sends the question to the LLM. When the LLM asks
for a tool call (for example `assess_run(125846)`), the harness forwards the call to the right MCP
server and feeds the result back. It repeats this until the LLM gives a final answer. The harness
also decides which MCP servers and instructions the LLM has.
- **HEP Genesis** is the harness, installed through Mu2e's aitools (`aitools/harness/hep-genesis`, which pins Mu2e/hep-genesis-agent). See assistant/README.md for the setup. It is domain-neutral, so Mu2e-specific code does not go
  into its core. Mu2e plugs in only through its own MCP server and a skill file.
- **Headless Claude Code** was used for testing, with `--mcp-config` pointing at dqm-assistant and
  `--append-system-prompt` loading the skill.

**Orchestrator.** In practice the same thing as the harness. The word stresses that it can
coordinate several MCP servers at once, for example dqm-assistant together with a runs database.

**Skill file** (`assistant/skills/mu2e-dqm.md`). Instructions for the LLM on how to use the
tools well. For example: call `assess_run` first, then report the verdict and the issue groups.
It is written for the LLM, not executed as code. The server sends its body as its MCP instructions at initialize, so every harness gets it without extra setup.

**Detector / method.** Something that judges a run and returns `Finding`s, each with a
`MethodCard` describing the method and its known false-alarm modes. Detectors are plugins, so the
assistant is method-agnostic.

## dqm-assistant tools

| Tool | Purpose |
|---|---|
| `assess_run(run)` | Full assessment of a run: verdict plus grouped, classified issues. The usual first call. |
| `get_findings(run, method=)` | The raw findings for a run, optionally limited to one method. |
| `compare(run, item, method=)` | Compares one item (for example a histogram) with its reference. |
| `history(item, run_min, run_max)` | How an item behaved over a range of runs. Used for onset and persistence. |
| `list_flagged(since_run=, cls=)` | Runs flagged so far, optionally by class. |
| `list_methods()` | The detectors configured for a subsystem. |
| `get_reference(run)` | The reference run used for a given run. |

## Why it is split this way

- **Detectors** answer a narrow question with a score. They know nothing about other runs or other
  methods. tranad-score is kept separate so the scoring service and its torch dependency can live
  elsewhere, for example behind `dqm_pipeline`.
- **dqm-assistant** holds the domain logic that should not depend on an LLM: memory across runs,
  onset detection, run-type context, false-alarm modes, and cross-method corroboration. Its output
  is deterministic and covered by tests.
- **The LLM and harness** handle the conversation: they turn questions into tool calls, chain
  follow-ups (`history`, `compare`, ...) and write the explanation.

Because the interface is MCP, the same server works with Genesis, Claude Code, or any other
MCP-capable client.

dqm-assistant can optionally call an LLM itself to write report text (`assistant/dqm_assistant/llm.py`).
Run it with `--no-llm` to leave all reasoning to the harness's LLM. The Claude Code test did this.

## Further reading

- `assistant/README.md`: package layout, running the server, writing a detector, hep-genesis setup.
- `assistant/DESIGN.md`: the full L1/L2/L3 design.
- `assistant/PLAN_hists_refs.md`: plan for histogram sources and references.
- `method-scores/SCHEMA.md`: the method output contract.
- `tranad-score/README.md`: the TranAD scoring CLI.

## Methods behind dqm-assistant

The agent talks only to dqm-assistant. No method is exposed to the agent directly, because
raw scores skip the layer that knows each method's false alarms, the onset and the
corroboration. What every method shares is the `Finding` + `MethodCard` interface, not a
transport:

| How a method's result arrives | Used for | Why |
|---|---|---|
| in-process detector | KS | cheap, no extra dependencies |
| DQM database (`dqm_alarms`) | limits, crv_ml | already computed by the DQM driver |
| `remote` detector reading [dqm-method-scores/1](method-scores/SCHEMA.md) by command, HTTP or file | TranAD (tranad-score) | own env (torch), model files, possibly a GPU |

A method that emits the schema needs only a config entry and a card, with no new code in
dqm-assistant. The long-term route is for methods to write their results to the DQM
database, so dqm-assistant reads them all the same way.
