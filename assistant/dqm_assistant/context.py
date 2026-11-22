"""What a detector and the assessor know about the run being judged (step 2)."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from dqm_assistant.references import Reference

# Run types whose flags are explained by the run type itself (step 4, "expected").
EXPECTED_RUN_TYPES = {"led", "empty", "calibration", "test"}


@dataclass
class RunContext:
    run: int
    subsystem: str
    sid: int
    source_version: str
    items: List[str]
    hists: Any                          # HistSource (or a fake in tests)
    reference: Optional[Reference] = None
    run_type: str = "unknown"
    period: Optional[str] = None
    reader: Any = None
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def reference_id(self) -> Optional[str]:
        return self.reference.key if self.reference else None

    @property
    def reference_runs(self) -> List[int]:
        return self.reference.runs if self.reference else []

    def hist(self, item: str):
        return self.hists.hist(self.run, item)

    def reference_hist(self, item: str):
        return self.hists.summed(self.reference.runs, item) if self.reference else None

    def summary(self) -> Dict[str, Any]:
        return {"run": self.run, "subsystem": self.subsystem, "source_version": self.source_version,
                "run_type": self.run_type, "period": self.period, "reference": self.reference_id,
                "reference_runs": self.reference_runs, **self.extra}


def period_for(run: int, periods_csv: Optional[str]) -> Optional[str]:
    """`period,start_run,end_run` rows (as mu2e_tranad/configs/periods_005-001.csv)."""
    if not periods_csv:
        return None
    with open(periods_csv) as f:
        for row in csv.DictReader(f):
            if int(row["start_run"]) <= run <= int(row["end_run"]):
                return row["period"]
    return None
