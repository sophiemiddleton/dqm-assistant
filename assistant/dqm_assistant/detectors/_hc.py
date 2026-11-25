"""Shared glue for the histogram methods from mu2e-histcompare (ks, vision, hydra).

mu2e_histcompare returns one Result(method, histogram, verdict, score, detail, evidence)
per histogram; this turns it into a Finding. The method itself (thresholds, rendering,
models) lives in mu2e-histcompare; the detectors here add only the MethodCard and the
item/run bookkeeping.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from dqm_assistant.context import RunContext
from dqm_assistant.findings import BAD, GOOD, UNSURE, Finding


def base(det, ctx: RunContext, item: str, reference: Optional[str] = "ctx") -> Dict[str, Any]:
    """The Finding fields every histogram detector fills the same way."""
    ref = ctx.reference_id if reference == "ctx" else reference
    return dict(run=ctx.run, subsystem=ctx.subsystem, item=item, method=det.name,
                method_version=det.version, reference=ref)


def unsure(fields: Dict[str, Any], note: str) -> Finding:
    return Finding(flag=UNSURE, evidence={"note": note}, **fields)


def to_finding(result, fields: Dict[str, Any], threshold: Optional[float] = None,
               **evidence) -> Finding:
    """A mu2e_histcompare Result -> Finding; no verdict (None) becomes UNSURE."""
    flag = {"GOOD": GOOD, "BAD": BAD}.get(result.verdict or "", UNSURE)
    ev = {**result.evidence, **evidence}
    if result.verdict is None:
        ev.setdefault("note", result.detail)
    return Finding(flag=flag, score=result.score, threshold=threshold, evidence=ev, **fields)
