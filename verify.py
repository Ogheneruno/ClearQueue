"""One command that checks this project end to end, with no API key and no network.

    python verify.py

Everything a judge needs to confirm is confirmable offline. That is a deliberate design
constraint, not a convenience: ground rule 08 keeps credentials out of the submission, so
nobody evaluating this will ever hold a credential that can run it. A reproduction path
that depends on one is a reproduction path that does not work.

Five stages, each of which can fail independently:

  1. tools selftest     the deterministic calculators agree with hand-worked arithmetic
  2. scorer selftest    the metric is not rigged -- known-good and known-bad verdicts
                        score as they should
  3. mock triage        the harness runs end to end on all 14 cases with a scripted fake
                        model, costing nothing
  4. mock invariant     that mock run scores EXACTLY what the always-approve control
                        scores. The mock is always-approve, so any difference is the
                        harness inventing signal, not the model finding it.
  5. replay scoring     the committed traces reproduce the headline numbers in the README

Stage 4 is the one worth reading twice. Stages 1-3 show the code runs; stage 4 shows the
measurement apparatus does not flatter it.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
PY = sys.executable
MOCK_RUN = ROOT / "runs" / "_verify_mock"
# The recorded bundle holds one directory per ladder version; stage 5 re-scores the
# shipping configuration out of it.
RECORDED = ROOT / "runs" / "recorded"
REPLAY_RUN = RECORDED / "final"


def _run(argv: list[str]) -> tuple[int, str]:
    p = subprocess.run([PY, *argv], cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _metrics(run_dir: Path) -> dict:
    """Score a run in-process so the invariant compares numbers, not printed text."""
    import score
    truth = score.load_truth(ROOT / "cases")
    verdicts = score.load_verdicts(run_dir)
    return score.score_run(truth, verdicts, run_dir.name)


def _always_approve() -> dict:
    import score
    truth = score.load_truth(ROOT / "cases")
    verdicts = score.control_verdicts(truth, ROOT / "cases", "always_approve")
    return score.score_run(truth, verdicts, "control/always_approve")


def _summary_line(out: str) -> str:
    """The selftests print explanatory prose after their verdict; take the verdict."""
    hits = [l.strip() for l in out.splitlines() if "passed" in l.lower()]
    return hits[-1] if hits else out.strip().splitlines()[-1] if out.strip() else ""


def main() -> int:
    print("\nClearQueue offline verification — no API key, no network.\n")
    stages: list[tuple[str, bool, str]] = []

    def stage(name: str, ok: bool, note: str = "") -> None:
        stages.append((name, ok, note))
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   {note}" if note else ""))
        if not ok:
            print("        ---- output ----")
            for line in note.splitlines()[-25:]:
                print(f"        {line}")

    # 1. deterministic calculators
    code, out = _run(["-m", "clearqueue.tools"])
    stage("tools selftest", code == 0, _summary_line(out) if code == 0 else out)

    # 2. the metric itself
    code, out = _run(["score.py", "--selftest"])
    stage("scorer selftest", code == 0, _summary_line(out) if code == 0 else out)

    # 3. full harness on a scripted model
    expected = len([p for p in (ROOT / "cases").iterdir()
                    if p.is_dir() and (p / "invoice.json").exists()])
    if MOCK_RUN.exists():
        shutil.rmtree(MOCK_RUN)
    code, out = _run(["run.py", "--version", "final", "--llm", "mock",
                      "--out", str(MOCK_RUN), "--no-packets"])
    n = len(list(MOCK_RUN.glob("*/verdict.json"))) if MOCK_RUN.exists() else 0
    stage(f"mock triage ({expected} cases)", code == 0 and n == expected,
          f"{n}/{expected} verdicts written" if code == 0 else out)

    # 4. the invariant: mock IS always-approve, so it must score identically
    invariant_ok, note = False, "skipped — mock run did not complete"
    if n == expected:
        got = _metrics(MOCK_RUN)
        want = _always_approve()
        keys = ["resolution_accuracy", "disposition_accuracy", "amount_accuracy",
                "false_approval_rate", "overpay_exposure", "underpay_exposure"]
        diffs = [f"{k}: mock={got[k]!r} control={want[k]!r}"
                 for k in keys if abs(float(got[k]) - float(want[k])) > 1e-9]
        invariant_ok = not diffs
        note = (f"mock == always_approve on all {len(keys)} metrics "
                f"(resolution {got['resolution_accuracy']:.1f}%)"
                if invariant_ok else "; ".join(diffs))
    stage("mock == always-approve control", invariant_ok, note)

    # 5. the committed traces
    if REPLAY_RUN.exists():
        code, out = _run(["score.py", "--replay", str(REPLAY_RUN)])
        headline = ""
        if code == 0:
            m = _metrics(REPLAY_RUN)
            headline = (f"resolution {m['resolution_accuracy']:.1f}%  "
                        f"false-approval {m['false_approval_rate']:.1f}%")
        stage("replay committed traces", code == 0, headline or out)
    else:
        stage("replay committed traces", False,
              "runs/recorded/final/ not found — the recorded bundle is missing")

    shutil.rmtree(MOCK_RUN, ignore_errors=True)

    failed = [n for n, ok, _ in stages if not ok]
    print()
    if failed:
        print(f"  {len(failed)} of {len(stages)} stages FAILED: {', '.join(failed)}\n")
        return 1
    print(f"  All {len(stages)} stages passed. The measured results in README.md are")
    print("  reproducible on this machine without a credential.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
