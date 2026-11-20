"""TranAD via tranad-score: the generic `remote` detector plus TranAD's MethodCard.

Scoring (reading the run's DQM points, running dqm_pipeline's crv_ml evaluator) lives in
tranad-score/ (repo root), which emits dqm-method-scores/1. This plugin adds no
interpretation of its own: remote.to_findings applies the schema's rules (one Finding per
item per run, BAD if any subrun is flagged, carrying the worst subrun).

Two ways to run the scorer:

    # in-process: needs the anldq/torch env ($DQM_ASSISTANT_ENV) for dqm-assistant itself
    - {type: tranad, model: /path/crv_tranad_006-001.pkl, detectors: [tranad, drift]}

    # separate env: dqm-assistant needs no torch; the CLI reloads the model on every run
    - type: tranad
      command: [bash, -c, "source /path/setup_ana_env.sh >/dev/null 2>&1 &&
                python -m tranad_score --model /path/m.pkl --sid {sid} {run}"]

Use `dqm_alarms` (algo crv_ml) instead once crv_ml commits its alarms through the DQM driver.
tranad-score is found on PYTHONPATH, or else as the sibling directory ../tranad-score.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from dqm_assistant.context import RunContext
from dqm_assistant.detectors.base import register
from dqm_assistant.detectors.remote import RemoteDetector
from dqm_assistant.findings import MethodCard

SIBLING = Path(__file__).resolve().parents[3] / "tranad-score"


def _scorer_class():
    try:
        from tranad_score import Scorer
    except ImportError:
        sys.path.insert(0, str(SIBLING))
        from tranad_score import Scorer
    return Scorer


@register("tranad")
class TranADDetector(RemoteDetector):
    card = MethodCard(
        name="tranad",
        compares="multivariate DQM metric history (TranAD reconstruction error, per subrun)",
        granularity="run (all metrics of the source)",
        needs_reference=False,
        blind_spots=("faults hidden when training spread is inflated by mixed configuration "
                     "periods or empty runs", "only the metrics in the DQM database"),
        false_alarms=("training_drift on empty runs",
                      "threshold set from training percentiles, not from labelled runs"),
        calibrated=False,
    )

    def __init__(self, model: Optional[str] = None, detectors=("tranad", "drift"),
                 config: str = "dqm-assistant", threshold_scale: float = 1.0, **options):
        super().__init__(**options)
        if not (model or self.command or self.url or self.path):
            raise ValueError("tranad needs a model (in-process) or a command/url/path transport")
        self.model, self.detectors = model, list(detectors)
        self.config, self.threshold_scale = config, threshold_scale
        self.version = Path(model).name if model else "remote"
        self._scorers: Dict[int, Any] = {}

    def _scorer(self, sid: int):
        if sid not in self._scorers:
            self._scorers[sid] = _scorer_class()(self.model, sid, detectors=self.detectors,
                                                 threshold_scale=self.threshold_scale,
                                                 config=self.config)
        return self._scorers[sid]

    def fetch(self, ctx: RunContext) -> Dict[str, Any]:
        if self.command or self.url or self.path:
            return super().fetch(ctx)
        return self._scorer(ctx.sid).score_run(ctx.reader, ctx.run)
