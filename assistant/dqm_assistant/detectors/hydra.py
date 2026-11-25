"""Hydra-style CNN on each histogram's image, no reference: mu2e_histcompare.hydra.

One small classifier per histogram, trained beforehand by mu2e-hydra
(`python -m hydra_mu2e.realdata run ...`, which saves <out>/models/<histogram>.pt);
`models` is that directory. The score is P(BAD), BAD above `threshold`. A histogram
without a model is UNSURE, not GOOD. Needs torch (install.sh --hydra).

Like JLab's Hydra it judges the plot alone, so it still works when no reference is
approved, and it cannot inherit a fault in the reference -- which makes it a useful
cross-check on KS and vision.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from dqm_assistant.context import RunContext
from dqm_assistant.detectors import _hc
from dqm_assistant.detectors.base import Detector, register
from dqm_assistant.findings import Finding, MethodCard


@register("hydra")
class HydraDetector(Detector):
    card = MethodCard(
        name="hydra",
        compares="histogram image alone, by a CNN trained per histogram (no reference)",
        granularity="histogram",
        needs_reference=False,
        blind_spots=("only the plot's shape as a 128x128 image: no absolute rate or normalisation",
                     "fault types not seen in training: unfamiliar shapes tend to come out GOOD",
                     "histograms without a trained model"),
        false_alarms=("trained on unchecked 'good' runs with injected faults: a fault present in "
                      "the training runs is learned as normal",
                      "channel-plot CNN false-alarms on ~25% of held-out normal 006-001 images",
                      "shapes that changed with the detector era (PE after ~125026) are judged "
                      "against the training era"),
        calibrated=False,
    )

    def __init__(self, models: str, threshold: float = 0.5, **options):
        super().__init__(**options)
        self.models = Path(models)
        if not self.models.is_dir():
            raise FileNotFoundError(f"hydra: models directory {self.models} does not exist")
        self.threshold = float(threshold)
        self.version = f"hydra:{self.models.parent.name if self.models.name == 'models' else self.models.name}"

    def assess(self, ctx: RunContext) -> List[Finding]:
        from mu2e_histcompare import hydra

        out = []
        for item in ctx.items:
            fields = _hc.base(self, ctx, item, reference=None)   # judges the plot alone
            h = ctx.hist(item)
            if h is None:
                out.append(_hc.unsure(fields, "histogram missing"))
                continue
            r = hydra.compare(h, item, self.models, self.threshold)
            out.append(_hc.to_finding(r, fields, threshold=self.threshold))
        return out
