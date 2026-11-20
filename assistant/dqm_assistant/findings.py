"""The data every layer agrees on: findings (L1 output), method cards, and the run report (L2 output).

Nothing in here knows about KS, TranAD or any other method. A detector is free to
compute whatever it likes; what it hands back is a list of `Finding`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

GOOD, BAD, UNSURE = "GOOD", "BAD", "UNSURE"

# Step 4 classes (DESIGN.md). Order matters only for display.
EXPECTED = "expected"            # explained by run type or a known change
PERSISTENT = "persistent"        # also flagged in recent runs
NEW = "new"                      # first seen in this run
REFERENCE_ARTEFACT = "reference_artefact"  # likely the reference, not the run
METHOD_ARTEFACT = "method_artefact"        # one method only, in a known false-alarm mode
CLASSES = (NEW, PERSISTENT, REFERENCE_ARTEFACT, METHOD_ARTEFACT, EXPECTED)


@dataclass(frozen=True)
class MethodCard:
    """What a method compares and how it is known to fail -- lets the agent weigh it."""

    name: str
    compares: str                     # "shape vs reference", "metric vs limits", "metric history"
    granularity: str                  # "histogram", "metric", "run"
    needs_reference: bool
    blind_spots: Tuple[str, ...] = ()
    false_alarms: Tuple[str, ...] = ()
    calibrated: bool = False          # threshold set against labelled/expert-confirmed data?

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Finding:
    """One method's verdict on one item of one run. The only L1 -> L2 interface."""

    run: int
    subsystem: str
    item: str                          # histogram path or metric name
    method: str
    method_version: str
    flag: str                          # GOOD / BAD / UNSURE
    score: Optional[float] = None
    threshold: Optional[float] = None
    subrun: Optional[int] = None
    reference: Optional[str] = None    # reference id@version, or "history:<N>"
    locus: Optional[str] = None        # e.g. "channels 1024-1535", "FEB 12"
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Finding":
        return cls(**d)


@dataclass
class Group:
    """Findings that probably share one cause (step 3)."""

    key: str
    findings: List[Finding]
    name: str = ""
    cls: str = NEW
    reason: str = ""
    methods_bad: List[str] = field(default_factory=list)
    methods_good: List[str] = field(default_factory=list)
    onset_run: Optional[int] = None
    onset_is_lower_bound: bool = False  # streak reaches the earliest assessed run: onset is at or before it
    confidence: str = "medium"         # low / medium / high

    @property
    def items(self) -> List[str]:
        return sorted({f.item for f in self.findings})

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["items"] = self.items
        d["findings"] = [f.to_dict() for f in self.findings]
        return d


@dataclass
class RunReport:
    run: int
    subsystem: str
    verdict: str                       # GOOD / BAD / NEEDS-EXPERT
    summary: str
    groups: List[Group]
    context: Dict[str, Any]
    not_checked: List[str]
    next_step: str
    methods: List[str]
    created: str
    llm_model: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["groups"] = [g.to_dict() for g in self.groups]
        return d
