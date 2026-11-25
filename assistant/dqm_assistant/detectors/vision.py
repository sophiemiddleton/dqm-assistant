"""Vision-LLM review of each histogram against its reference, reusing mu2e-vision.

Needs HistCompare/mu2e-vision on PYTHONPATH and LITELLM_API_KEY. One model call per
histogram, so it is the slow, costly detector: enable it per subsystem in the config.
"""

from __future__ import annotations

from typing import List

import yaml

from dqm_assistant.context import RunContext
from dqm_assistant.detectors.base import Detector, register
from dqm_assistant.findings import BAD, GOOD, UNSURE, Finding, MethodCard


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

    def __init__(self, instructions: str, model: str = "azure/claude-opus-5-5",
                 base_url: str = "https://litellm.fnal.gov/v1", **options):
        super().__init__(**options)
        self.plots = yaml.safe_load(open(instructions))["plots"]
        self.model, self.base_url = model, base_url
        self.version = model

    def assess(self, ctx: RunContext) -> List[Finding]:
        from histcompare.context import render, user_content, xlabel_for
        from histcompare.vision import OpenAIReviewer

        reviewer = OpenAIReviewer(self.base_url, self.model)
        out = []
        for item in ctx.items:
            name = item.rsplit("/", 1)[-1]
            base = dict(run=ctx.run, subsystem=ctx.subsystem, item=item, method=self.name,
                        method_version=self.version, reference=ctx.reference_id)
            instr, h, ref = self.plots.get(name), ctx.hist(item), ctx.reference_hist(item)
            if instr is None or h is None or ref is None:
                out.append(Finding(flag=UNSURE, evidence={"note": "no instructions, histogram or reference"}, **base))
                continue
            xl = instr.get("xlabel") or xlabel_for(name)
            content = user_content(name, str(ctx.run), ctx.run_type, ctx.reference_runs[0], instr,
                                   render(h, instr.get("title", name), xl, f"run {ctx.run}"),
                                   render(ref, instr.get("title", name), xl, "reference"))
            text, verdict = reviewer.review(content)
            flag = {"GOOD": GOOD, "BAD": BAD}.get(verdict or "", UNSURE)
            out.append(Finding(flag=flag, evidence={"text": text}, **base))
        return out
