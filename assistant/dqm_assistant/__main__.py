"""CLI without MCP, for testing and replays.

    python -m dqm_assistant --config config.yaml assess 125846
    python -m dqm_assistant --config config.yaml replay 124189 124228 ... 125850   # in run order
"""

from __future__ import annotations

import argparse
import json

from dqm_assistant.service import Service


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="dqm_assistant")
    ap.add_argument("--config", required=True)
    ap.add_argument("--subsystem", default="CRV")
    ap.add_argument("--no-llm", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("assess"); p.add_argument("run", type=int); p.add_argument("--refresh", action="store_true")
    p = sub.add_parser("replay"); p.add_argument("runs", type=int, nargs="+")
    a = ap.parse_args(argv)

    s = Service(a.config, use_llm=not a.no_llm)
    if a.cmd == "assess":
        print(json.dumps(s.assess_run(a.run, a.subsystem, a.refresh), indent=1, default=str))
    else:
        for run in sorted(a.runs):                    # history needs earlier runs first
            r = s.assess_run(run, a.subsystem, refresh=True)
            groups = "; ".join(f"[{g['cls']}] {g['name'] or g['key']}" for g in r["groups"])
            print(f"{run}  {r['verdict']:<12} {groups}")


if __name__ == "__main__":
    main()
