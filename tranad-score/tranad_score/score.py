"""Score one run's DQM points with a trained mu2e_tranad (TranAD) model.

This is the "score this run" service, kept apart from any orchestrator: it reads the run's
points from the DQM database, runs the DQM `tranad` evaluator on them (the same code the
DQM driver runs), and returns plain JSON. It knows nothing about dqm-assistant, reports,
references or other methods, and writes nothing to the database.

It only *uses* dqm.evaluate.tranad.TranADEvaluator and the mu2e_tranad model bundle;
nothing in either repo is changed.

    from tranad_score import Scorer
    s = Scorer(model="/path/crv_tranad_006-001.pkl", sid=118)
    s.score_run(reader, 125846)

Output: one dqm-method-scores/1 document per run (../method-scores/SCHEMA.md):

    {"schema": "dqm-method-scores/1", "method": "tranad", "method_version": <model file>,
     "sid", "run", "granularity": "subrun", "n_scored": <points scored>,
     "items": ["tranad_outlier", "training_drift"], "reference": "history:<lookback>",
     "results": [{"item", "subrun", "flag": "BAD", "score", "threshold", "top": [...]}, ...],
     "params": {"detectors", "threshold_scale"}}

Only flagged (subrun, item) pairs are listed -- TranADEvaluator reports nothing for a point
that passes, and the schema reads an unlisted item as GOOD. n_scored == 0 means the run has
no points for this source. For training_drift, score is the largest |shift| in sigma and
threshold is the drift sigma: the evaluator's own rule (drifted iff |shift| > sigma).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

SCHEMA = "dqm-method-scores/1"
SUBJECTS = {"tranad": "tranad_outlier", "pca": "pca_outlier", "drift": "training_drift"}


class Scorer:
    """One trained model applied to one DQM source (sid). Loads the model once, reuses it."""

    def __init__(self, model: str, sid: int, detectors: Sequence[str] = ("tranad", "drift"),
                 threshold_scale: float = 1.0, config: str = "tranad-score"):
        try:  # the evaluator lives in Mu2e/DQM (dqm.evaluate.tranad)
            from dqm.evaluate.tranad import TranADEvaluator
        except ImportError:  # older installs: it was mu2e_tranad.evaluator.MLEvaluator
            from mu2e_tranad.evaluator import MLEvaluator as TranADEvaluator

        self.model, self.sid, self.detectors = str(model), int(sid), list(detectors)
        self.threshold_scale = float(threshold_scale)
        self._ev = TranADEvaluator(config, self.sid, pars={"model": self.model,
                                                           "detectors": self.detectors,
                                                           "threshold_scale": threshold_scale})
        self._ev.configure()
        self._history = None

    @property
    def model_name(self) -> str:
        return Path(self.model).name

    @property
    def subjects(self) -> List[str]:
        return [SUBJECTS[d] for d in self.detectors if d in SUBJECTS]

    def score_run(self, reader, run: int) -> Dict[str, Any]:
        from dqm.evaluate.points import History, load_points

        iv = reader.intervals(sid=self.sid, run=run, limit=None)
        points = [] if iv.empty else sorted(
            load_points(reader, self.sid, list(iv.iid)),
            key=lambda p: (p.start_run or 0, p.start_subrun or 0))
        if points and self._history is None:
            self._history = History(reader, self.sid)

        results: List[Dict[str, Any]] = []
        for p in points:
            for f in self._ev.evaluate(p, self._history.before(p, self._ev.lookback)):
                results.append(_result(f.subject, p.start_subrun, json.loads(f.note or "{}")))

        return {"schema": SCHEMA, "method": "tranad", "method_version": self.model_name,
                "sid": self.sid, "run": int(run), "granularity": "subrun",
                "n_scored": len(points), "items": self.subjects,
                "reference": f"history:{self._ev.lookback}", "direction": "higher_is_worse",
                "results": results,
                "params": {"detectors": self.detectors, "threshold_scale": self.threshold_scale}}


def _result(subject: str, subrun, note: Dict[str, Any]) -> Dict[str, Any]:
    """One TranADEvaluator alarm note -> one schema result (always BAD: passes are not reported)."""
    note.pop("model", None)                              # same for every result; in method_version
    top = note.pop("top", [])
    r: Dict[str, Any] = {"item": subject, "subrun": subrun, "flag": "BAD", "top": top}
    if "score" in note:                                  # tranad / pca outlier
        r["score"], r["threshold"] = float(note.pop("score")), float(note.pop("threshold"))
    elif "sigma" in note and top:                        # training_drift: |shift| vs sigma
        r["score"] = max(abs(float(d.get("shift", 0.0))) for d in top)
        r["threshold"] = float(note["sigma"])
    if note:
        r["evidence"] = note                             # drifted, sigma, window, ...
    return r

def score_run(reader, sid: int, run: int, model: str, **options) -> Dict[str, Any]:
    """One-shot convenience; build a Scorer yourself to score many runs with one model load."""
    return Scorer(model, sid, **options).score_run(reader, run)
