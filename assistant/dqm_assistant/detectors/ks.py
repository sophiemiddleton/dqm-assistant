"""KS shape test against the reference: mu2e_histcompare.ks (DJ's dqm.hist.compare).

The thresholds are mu2e-histcompare's for two independent runs (independent=True,
tight 0.05, loose 0.01), not dqm.hist.compare's defaults (0.999 / 0.99, meant for
comparing a sample with itself), so the assistant and the histcompare studies give the
same verdict on the same histogram. BAD when the KS probability is below `loose`.
"""

from __future__ import annotations

from typing import List

from dqm_assistant.context import RunContext
from dqm_assistant.detectors import _hc
from dqm_assistant.detectors.base import Detector, register
from dqm_assistant.findings import Finding, MethodCard


@register("ks")
class KSDetector(Detector):
    card = MethodCard(
        name="ks",
        compares="histogram shape vs reference (ROOT KolmogorovTest probability)",
        granularity="histogram",
        needs_reference=True,
        blind_spots=("normalisation", "where in the histogram the difference is"),
        false_alarms=("high statistics: almost any real difference is significant "
                      "(86/120 BAD on 006-001)",
                      "inherits any fault in the reference"),
        calibrated=False,
    )

    def __init__(self, tight: float = 0.05, loose: float = 0.01, **options):
        super().__init__(**options)
        self.tight, self.loose = float(tight), float(loose)
        self.version = f"mu2e_histcompare.ks/dqm.hist.compare (tight {self.tight:g}, loose {self.loose:g})"

    def assess(self, ctx: RunContext) -> List[Finding]:
        from mu2e_histcompare import ks

        out = []
        for item in ctx.items:
            fields = _hc.base(self, ctx, item)
            h, ref = ctx.hist(item), ctx.reference_hist(item)
            if h is None or ref is None:
                out.append(_hc.unsure(fields, "histogram missing" if h is None else "no reference"))
                continue
            r = ks.compare(h, ref, item, self.tight, self.loose)
            p, d = r.evidence["ks_probability"], r.evidence["max_cdf_difference"]
            # Reported as the difference itself (small = similar), with a plain reading:
            # agents misread an "agreement" fraction.
            out.append(_hc.to_finding(r, fields, threshold=self.loose,
                                      reading=(f"KS p-value {p:.2g} (BAD below {self.loose:g}); the "
                                               f"normalised cumulative distributions differ by at "
                                               f"most {d:.1%} (0% = identical shapes)")))
        return out
