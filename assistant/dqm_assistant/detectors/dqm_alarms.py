"""Any evaluator that already runs in the Mu2e DQM driver: read its alarms from the database.

TranAD (`crv_ml`, see dqm_pipeline/evaluator.py) and the limits evaluator already write
episodes to dqm.alarms with per-interval evidence in dqm.alarm_causes. Rather than
re-running them here, this plugin reads what they decided. One instance per `algo`:

    - {type: dqm_alarms, algo: crv_ml, card: tranad}
    - {type: dqm_alarms, algo: limits, card: limits}
"""

from __future__ import annotations

from typing import Dict, List

from dqm_assistant.context import RunContext
from dqm_assistant.detectors.base import Detector, register
from dqm_assistant.findings import BAD, Finding, MethodCard

CARDS: Dict[str, MethodCard] = {
    "tranad": MethodCard(
        name="tranad",
        compares="multivariate metric history (TranAD reconstruction error)",
        granularity="run/subrun over all CRV metrics",
        needs_reference=False,
        blind_spots=("faults hidden when training spread is inflated by mixed "
                     "configuration periods or empty runs",),
        false_alarms=("drift alarms on empty runs",),
        calibrated=False,
    ),
    "limits": MethodCard(
        name="limits",
        compares="metric vs hand-set band (dqm.limits)",
        granularity="metric",
        needs_reference=False,
        blind_spots=("anything the band was not set for",),
        false_alarms=("band set for a different configuration period",),
        calibrated=True,
    ),
}


@register("dqm_alarms")
class DqmAlarmsDetector(Detector):
    version = "dqm.alarms"

    def __init__(self, algo: str, card: str, **options):
        super().__init__(**options)
        self.algo = algo
        self.card = CARDS[card]

    @property
    def method_id(self) -> str:
        return self.card.name

    def assess(self, ctx: RunContext) -> List[Finding]:
        from dqm_assistant.dqmdb import rows_for_ids

        r = ctx.reader
        iv = r.intervals(sid=ctx.sid, run=ctx.run, limit=None)
        if iv.empty:
            return []
        causes = rows_for_ids(r, "alarm_causes", "iid", iv.iid)
        if causes.empty:
            return []                       # no alarm = this method saw nothing (GOOD implied)
        alarms = rows_for_ids(r, "alarms", "aid", causes.aid)
        alarms = alarms[alarms.algo == self.algo]
        names = {v.vid: f"{v.groupx},{v.subgroup},{v.namex}" for v in r.values().itertuples()}
        subrun = dict(zip(iv.iid, iv.start_subrun))

        out = []
        for a in alarms.itertuples():
            for c in causes[causes.aid == a.aid].itertuples():
                item = names.get(c.vid, f"{a.subject} (global)") if c.vid == c.vid else f"{a.subject} (global)"
                out.append(Finding(
                    run=ctx.run, subsystem=ctx.subsystem, item=item, method=self.card.name,
                    method_version=f"{self.algo}:{a.config}", flag=BAD, score=float(c.level),
                    subrun=int(subrun.get(c.iid, 0)) or None, reference=None,
                    evidence={"aid": int(a.aid), "subject": a.subject, "episode_level": int(a.level),
                              "status": a.status},
                ))
        return out
