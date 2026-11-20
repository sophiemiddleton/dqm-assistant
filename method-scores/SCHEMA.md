# dqm-method-scores/1

The output contract for a DQM anomaly method that runs outside dqm-assistant. Each document
is one method's verdict on one run of one DQM source. A method that emits this format needs
no adapter code in dqm-assistant: the generic `remote` detector reads it, and the subsystem
config supplies a `MethodCard` for the method.

The document carries **scores, not interpretation**. The method says what it measured and
where it crossed its own threshold. dqm-assistant decides what that means: grouping,
onset, classification, corroboration and known false alarms.

Producers today: `tranad-score` (TranAD, drift). Machine-readable form:
[dqm-method-scores-1.schema.json](dqm-method-scores-1.schema.json).

## Example

```json
{
  "schema": "dqm-method-scores/1",
  "method": "tranad",
  "method_version": "crv_tranad_006-001.pkl",
  "sid": 118,
  "run": 122834,
  "granularity": "subrun",
  "n_scored": 28,
  "items": ["tranad_outlier", "training_drift"],
  "reference": "history:20",
  "direction": "higher_is_worse",
  "results": [
    {"item": "tranad_outlier", "subrun": 4, "flag": "BAD",
     "score": 6.1, "threshold": 2.0,
     "top": [{"metric": "crvreco/kpp_crv/PEs", "error": 3.2}]}
  ],
  "params": {"detectors": ["tranad", "drift"], "threshold_scale": 1.0}
}
```

## Fields

### Top level

| Field | Req. | Meaning |
|---|---|---|
| `schema` | yes | Always `"dqm-method-scores/1"`. A consumer rejects other values. |
| `method` | yes | Method family, for example `tranad` or `ks`. It is matched to a `MethodCard`. |
| `method_version` | yes | What produced the scores: a model file, a code version or a config hash. Two runs scored with different versions are not directly comparable. |
| `sid` | yes | DQM source id. |
| `run` | yes | Run number. |
| `granularity` | yes | `"subrun"` (one score per subrun) or `"run"` (one per run). |
| `n_scored` | yes | How many units (subruns, or 1 for a run) had data and were scored. **0 means the method had no data for this run**, so the run is not judged and no finding is made. |
| `items` | yes | Every item the method judged for this run. An item is a histogram path, a metric name, or a method-level subject such as `tranad_outlier`. |
| `results` | yes | Per-item, per-unit results; see below. May be empty. |
| `reference` | no | What the run was compared with: `"<id>@<version>"` for a reference, `"history:<N>"` for the previous N points, or null. |
| `direction` | no | `"higher_is_worse"` (default) or `"lower_is_worse"` (p-values, agreement fractions). It tells the consumer how to rank results by how far past the threshold they are. |
| `params` | no | Method settings worth recording. Free form; kept as evidence. |
| `error` | no | A message, if the method failed for the whole run. `n_scored` must then be 0. |

### Results

| Field | Req. | Meaning |
|---|---|---|
| `item` | yes | One of `items`. |
| `flag` | yes | `"BAD"` (threshold crossed), `"UNSURE"` (could not be judged: too few entries, fit failed, and so on) or `"GOOD"`. |
| `subrun` | no | The subrun, for `granularity: "subrun"`. Omitted or null for run-level results. |
| `score` | no | The method's statistic for this unit. |
| `threshold` | no | The cut it was compared with, after any scaling. With `higher_is_worse`, BAD means `score > threshold`. |
| `locus` | no | Where inside the item, if the method knows: `"channels 1024-1535"`, `"FEB 12"`. |
| `top` | no | Contributing inputs, worst first: `[{"metric": ..., ...}]`. Any extra keys (error, shift, value) are kept. |
| `evidence` | no | Anything else, free form. Unknown top-level keys of a result are folded into it as well. |

## Rules

1. **An item listed in `items` with no BAD or UNSURE result is GOOD for the run.** A method
   may list only its flagged units (as dqm_pipeline's `MLEvaluator` does), or list every unit
   with explicit `GOOD` results. Both mean the same thing.
2. **One finding per item per run.** If any unit of an item is BAD, the item is BAD for the
   run. Its finding carries the worst unit, ranked by score/threshold (inverted for
   `lower_is_worse`), and records how many units were flagged out of `n_scored`. If the item
   has no BAD unit but has an UNSURE one, it is UNSURE.
3. **No data is not GOOD.** `n_scored: 0` gives no finding at all, so the assessor reports
   the method as not checked, never as passing.
4. **The method's own threshold decides BAD.** The consumer does not re-cut the scores. How
   much to trust the threshold is a property of the method (`MethodCard.calibrated`,
   `false_alarms`), and that lives with the consumer.
5. **Additive changes keep version 1.** New optional fields may appear. Consumers ignore
   fields they do not know. Renaming or changing the meaning of a field means
   `dqm-method-scores/2`.

## Transports

The same document can arrive in any of these ways. The generic `remote` detector in
dqm-assistant supports all except MCP:

| Transport | Config | Use |
|---|---|---|
| in-process | a Python subclass of `RemoteDetector` that overrides `fetch` | the method imports cleanly into the assistant's env |
| command | `command: [python, -m, tranad_score, ..., --sid, "{sid}", "{run}"]` | a separate env, no server; one JSON document per line on stdout |
| http | `url: http://host:port/score` (POST `{"sid", "run"}`) | a method service, such as the planned `dqm_pipeline.serve` |
| file | `path: /dir/{sid}/{run}.json` | replay, tests, or scores written by a batch job |
| MCP | (not built) | a method service exposed as an MCP tool with the same document as its result |

The long-term route is for methods to write these documents, or the alarms they summarise,
to the DQM database, so the assistant reads every method the same way.
