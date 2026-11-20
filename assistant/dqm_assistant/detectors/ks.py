"""KS / fraction shape test against the reference -- DJ's dqm.hist.compare, unchanged."""

from __future__ import annotations

from typing import List

from dqm_assistant.context import RunContext
from dqm_assistant.detectors.base import Detector, register
from dqm_assistant.findings import BAD, GOOD, UNSURE, Finding, MethodCard


@register("ks")
class KSDetector(Detector):
    version = "dqm.hist.compare"
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

    def assess(self, ctx: RunContext) -> List[Finding]:
        from dqm.hist.compare import CompareStatus, compare_histograms

        out = []
        for item in ctx.items:
            base = dict(run=ctx.run, subsystem=ctx.subsystem, item=item, method=self.name,
                        method_version=self.version, reference=ctx.reference_id)
            h, ref = ctx.hist(item), ctx.reference_hist(item)
            if h is None or ref is None:
                why = "histogram missing" if h is None else "no reference"
                out.append(Finding(flag=UNSURE, evidence={"note": why}, **base))
                continue
            c = compare_histograms(h, ref, path=item)
            flag = {CompareStatus.fail: BAD, CompareStatus.cantCompare: UNSURE}.get(c.status, GOOD)
            p, d = float(c.kolmogorov), 1.0 - float(c.fraction)
            out.append(Finding(flag=flag, score=p,
                               evidence={"status": c.status.name,
                                         "ks_probability": p,
                                         # c.fraction = 1 - largest |difference| of the normalised
                                         # cumulative sums. Reported as the difference itself (small =
                                         # similar), with a plain reading: agents misread "agreement".
                                         "max_cdf_difference": round(d, 4),
                                         "reading": (f"KS p-value {p:.2g}; the normalised cumulative "
                                                     f"distributions differ by at most {d:.1%} "
                                                     f"(0% = identical shapes)"),
                                         "note": c.note}, **base))
        return out
