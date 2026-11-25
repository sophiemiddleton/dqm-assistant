"""Vision-LLM review of each histogram against its reference: mu2e_histcompare.vision.

The model sees the reference plot, the run's plot and that plot's written instructions
(mu2e-histcompare bundles mu2e-vision's instructions: give a name such as
`crv_real_draft`, or a path to a YAML). Needs LITELLM_API_KEY for the LiteLLM gateway.
One model call per histogram, so it is the slow, costly detector: enable it per
subsystem in the config.
"""

from __future__ import annotations

from typing import List, Optional

from dqm_assistant.context import RunContext
from dqm_assistant.detectors import _hc
from dqm_assistant.detectors.base import Detector, register
from dqm_assistant.findings import Finding, MethodCard


@register("vision")
class VisionDetector(Detector):
    card = MethodCard(
        name="vision",
        compares="histogram image vs reference image, with written plot instructions",
        granularity="histogram",
        needs_reference=True,
        blind_spots=("only what the instructions describe and the image shows",),
        false_alarms=("inherits any fault in the reference", "non-deterministic"),
        calibrated=False,
    )

    def __init__(self, instructions: str = "crv_real_draft", model: str = "azure/claude-opus-5-5",
                 base_url: Optional[str] = "https://litellm.fnal.gov/v1", effort: str = "high",
                 **options):
        super().__init__(**options)
        from mu2e_histcompare import instructions as bundled

        self.instructions = str(bundled.path(instructions))
        self.plots = bundled.load(instructions)
        self.model, self.base_url, self.effort = model, base_url, effort
        self.version = f"{model} ({bundled.path(instructions).stem})"

    def assess(self, ctx: RunContext) -> List[Finding]:
        from mu2e_histcompare import vision
        from mu2e_histcompare.result import short_name

        if self.base_url:
            # The reviewer reads LITELLM_API_KEY only; give it the same key the rest of
            # dqm-assistant uses (env, else ~/.litellm_key), so the server needs no extra setup.
            import os
            from dqm_assistant.llm import _key
            key = _key()
            if not key:
                raise RuntimeError("vision: no LiteLLM key (LITELLM_API_KEY or ~/.litellm_key)")
            os.environ.setdefault("LITELLM_API_KEY", key)
        reviewer = vision.make_reviewer(self.model, self.base_url, self.effort)
        out = []
        for item in ctx.items:
            fields = _hc.base(self, ctx, item)
            instr, h, ref = self.plots.get(short_name(item)), ctx.hist(item), ctx.reference_hist(item)
            if instr is None or h is None or ref is None:
                out.append(_hc.unsure(fields, "no instructions for this plot" if instr is None else
                                      "histogram missing" if h is None else "no reference"))
                continue
            r = vision.compare(h, ref, item, instr, reviewer, run=str(ctx.run),
                               ref_run=str(ctx.reference_runs[0]), run_type=ctx.run_type)
            out.append(_hc.to_finding(r, fields, text=r.detail))
        return out
