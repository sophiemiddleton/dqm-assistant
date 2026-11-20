"""Reference registry (PLAN_hists_refs.md, Q2 Phase 0): versioned YAML, approved by a human.

Only `approved` entries are ever used. No match -> no reference, and the report says so;
nothing is silently compared against a stale or unapproved one.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import List, Optional

import yaml


@dataclass
class Reference:
    id: str
    version: int
    source_version: str
    run_type: str                      # "cosmics", "led", ... or "any"
    valid_runs: List[Optional[int]]    # [first, last]; last None = open-ended
    runs: List[int]                    # reference run(s), summed
    status: str = "candidate"          # candidate | approved | retired
    period: Optional[str] = None
    approved_by: Optional[str] = None
    date: Optional[str] = None
    checks: dict = field(default_factory=dict)
    note: str = ""

    @property
    def key(self) -> str:
        return f"{self.id}@v{self.version}"

    def covers(self, run: int) -> bool:
        lo, hi = self.valid_runs
        return (lo is None or run >= lo) and (hi is None or run <= hi)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["key"] = self.key
        return d


class Registry:
    def __init__(self, entries: List[Reference]):
        self.entries = entries

    @classmethod
    def load(cls, path: str) -> "Registry":
        raw = yaml.safe_load(open(path)) or []
        return cls([Reference(**e) for e in raw])

    def select(self, source_version: str, run: int, run_type: str = "any",
               period: Optional[str] = None) -> Optional[Reference]:
        ok = [r for r in self.entries
              if r.status == "approved" and r.source_version == source_version and r.covers(run)
              and r.run_type in ("any", run_type)
              and (period is None or r.period in (None, period))
              and run not in r.runs]                    # never judge a run against itself
        return max(ok, key=lambda r: (r.run_type != "any", r.version), default=None)
