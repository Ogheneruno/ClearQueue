"""Rebuild the counterfactual that measures what the v6 citation check is worth.

    python make_counterfactual.py

The problem with comparing `final` against `v3-rerun-unenforced` is that they are two
different runs, and this project has already demonstrated that run-to-run variance in the
citation column is large enough to invent a finding (see the v5 entry in CHANGELOG.md).
Attributing the v6 delta to the lever from that comparison would repeat the mistake.

So this script holds model behaviour fixed and removes only the check. It reads the committed
trajectories of the shipping run, finds the cases where the citation check fired, and rebuilds
the run with each of those cases carrying its **pre-retry** verdict -- the answer the harness
would have accepted had the check not existed. Everything else is byte-identical.

Scoring the result against `runs/recorded/final` is therefore a clean before/after on one
lever, with no second sample of the model involved.

    python score.py --table runs/recorded/final runs/recorded/v6-counterfactual-no-check

Nothing here re-derives an answer or contacts a model. It only replays what was recorded.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).parent
SRC = ROOT / "runs" / "recorded" / "final"
DST = ROOT / "runs" / "recorded" / "v6-counterfactual-no-check"


def main() -> int:
    if not SRC.exists():
        print(f"missing {SRC} -- the recorded bundle is not present")
        return 1

    if DST.exists():
        shutil.rmtree(DST)
    shutil.copytree(SRC, DST)

    patched = []
    for case_dir in sorted(DST.iterdir()):
        trace = case_dir / "trajectory.jsonl"
        if not trace.exists():
            continue
        events = [json.loads(l) for l in trace.read_text(encoding="utf-8").splitlines()]
        if not any(e.get("type") == "citation_rejected" for e in events):
            continue

        # The first final_message is what the model returned before it was asked for
        # provenance. That is precisely the verdict an unchecked harness would have kept.
        first = next(e for e in events if e.get("type") == "final_message")
        before = json.loads(first["text"])
        shipped = json.loads((case_dir / "verdict.json").read_text(encoding="utf-8"))
        before["_meta"] = shipped["_meta"]          # token/cost accounting is unchanged
        (case_dir / "verdict.json").write_text(json.dumps(before, indent=2), encoding="utf-8")
        patched.append((case_dir.name, before, shipped))

    print(f"rebuilt {DST.relative_to(ROOT)} from {SRC.relative_to(ROOT)}")
    print(f"the citation check fired on {len(patched)} of "
          f"{len(list(DST.glob('*/verdict.json')))} cases:\n")
    for name, before, shipped in patched:
        print(f"  {name}")
        print(f"    check off:  {before.get('disposition')} / {before.get('payable_amount')}"
              f"   citations={before.get('citations')}")
        print(f"    check on :  {shipped.get('disposition')} / {shipped.get('payable_amount')}"
              f"   citations={shipped.get('citations')}")
    print("\nnow score both:")
    print("  python score.py --table runs/recorded/final "
          "runs/recorded/v6-counterfactual-no-check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
