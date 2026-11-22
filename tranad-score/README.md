# tranad-score

The "score this run" service for TranAD, kept apart from the orchestrator (dqm-assistant).
Given a trained mu2e_tranad model and a DQM source id, it reads one run's points from the
DQM database, runs mu2e_tranad's `crv_ml` evaluator on them (the same code as the DQM
driver), and returns plain JSON. It writes nothing and knows nothing about dqm-assistant.

It only *imports* mu2e_tranad (`MLEvaluator`, public API, from github.com/sophiemiddleton/mu2e-tranad)
and changes nothing in that repo.

```bash
../install.sh --tranad                    # mu2e_tranad, torch, mu2e-dqm into ../.venv
../.venv/bin/tranad-score --model crv_tranad_006-001.pkl --sid 118 125846 122834
```

```python
from tranad_score import Scorer
s = Scorer(model, sid=118, detectors=["tranad", "drift"])
s.score_run(reader, 125846)
# {"schema": "dqm-method-scores/1", "method": "tranad", "method_version", "sid", "run",
#  "granularity": "subrun", "n_scored", "items", "reference", "results": [...], "params"}
```

The output is a [dqm-method-scores/1](../method-scores/SCHEMA.md) document, the common
contract for methods that run outside dqm-assistant. Only flagged (subrun, item) pairs are
listed: MLEvaluator returns nothing for a passing point, and the schema reads an unlisted item
as GOOD.

dqm-assistant reads it with its generic `remote` detector; `tranad` is that detector plus a
MethodCard and an in-process `Scorer`. With `transport: {command: [...]}` the assistant
instead runs this CLI in the torch env, so the assistant's own env needs no torch. Next step,
not built: an HTTP/MCP service (`mu2e_tranad.serve`) that keeps the model loaded.
