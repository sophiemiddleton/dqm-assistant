"""Run -> files -> one summed histogram per item (PLAN_hists_refs.md, Q1 Phase 0).

1. run -> file names from dqm.files (the same files the metrics came from),
2. name -> path: dqm.catalog.file_url if its `catalog` extra is installed, else the Mu2e
   rule it implements (sha256 of the name, first two bytes as two directory levels),
3. fallback for sources with no dqm.files rows (004/005): glob the dataset directory,
4. sum subruns (average the `mean` items, e.g. per-channel rate maps), cache per run.
"""

from __future__ import annotations

import hashlib
import logging
import pickle
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

LOG = logging.getLogger("dqm_assistant.histsource")


def mu2e_path(name: str, dataset_dir: Path) -> Path:
    try:
        from dqm.catalog import available, file_url
        if available():
            return Path(file_url(name))
    except ImportError:
        pass
    h = hashlib.sha256(name.encode()).hexdigest()
    return Path(dataset_dir) / "root" / h[:2] / h[2:4] / name


class HistSource:
    def __init__(self, sid: int, dataset_dir: str, items: Sequence[str], mean: Iterable[str] = (),
                 reader=None, cache_dir: Optional[str] = None):
        self.sid, self.dataset_dir, self.items = sid, Path(dataset_dir), list(items)
        self.mean, self.reader = frozenset(mean), reader
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self._mem: Dict[int, Dict[str, object]] = {}

    # ---- which files
    def file_names(self, run: int) -> List[str]:
        if self.reader is None:
            return []
        from dqm_assistant.dqmdb import rows_for_ids
        iv = self.reader.intervals(sid=self.sid, run=run, limit=None)
        if iv.empty:
            return []
        files = rows_for_ids(self.reader, "files", "iid", iv.iid)
        return sorted(files[files.sid == self.sid].filename)

    def files_for_run(self, run: int) -> List[Path]:
        names = self.file_names(run)
        if names:
            return [mu2e_path(n, self.dataset_dir) for n in names]
        LOG.info("run %s: no dqm.files rows for sid %s, globbing %s", run, self.sid, self.dataset_dir)
        return sorted(self.dataset_dir.glob(f"root/*/*/*.{run:06d}_*.root"))

    # ---- histograms
    def run_hists(self, run: int) -> Dict[str, object]:
        if run in self._mem:
            return self._mem[run]
        paths = self.files_for_run(run)
        cache = self.cache_dir / f"sid{self.sid}" / f"{run}.pkl" if self.cache_dir else None
        if cache and cache.exists():
            blob = pickle.loads(cache.read_bytes())
            if blob["files"] == [p.name for p in paths] and set(self.items) <= set(blob["hists"]):
                self._mem[run] = blob["hists"]
                return blob["hists"]
        hists = self._sum(paths)
        if cache:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(pickle.dumps({"files": [p.name for p in paths], "hists": hists}))
        self._mem[run] = hists
        return hists

    def _sum(self, paths: Sequence[Path]) -> Dict[str, object]:
        import uproot
        total: Dict[str, object] = {}
        n: Dict[str, int] = {}
        for p in paths:
            with uproot.open(p) as f:
                for item in self.items:
                    if item not in f:
                        continue
                    h = f[item].to_hist()
                    total[item] = h if item not in total else total[item] + h
                    n[item] = n.get(item, 0) + 1
        for item in self.mean & total.keys():
            total[item] = total[item] * (1.0 / n[item])
        return total

    def hist(self, run: int, item: str):
        return self.run_hists(run).get(item)

    def summed(self, runs: Sequence[int], item: str):
        hs = [h for h in (self.hist(r, item) for r in runs) if h is not None]
        if not hs:
            return None
        out = hs[0]
        for h in hs[1:]:
            out = out + h
        return out * (1.0 / len(hs)) if item in self.mean else out
