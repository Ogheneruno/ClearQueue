"""ClearQueue — accounts-payable exception triage.

    python run.py --version v1-baseline --llm mock      # free, no credential
    python run.py --version final --llm anthropic       # a scored run
    python run.py --ladder --llm anthropic              # every version, in order
    python run.py --review --out runs/final             # the human approval gate

Nothing in this program pays anything. It produces recommendations and the evidence behind
them; a named human approves or rejects each one.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from clearqueue import packet
from clearqueue.arms import solve_case
from clearqueue.config import LADDER, VERSIONS
from clearqueue.llm import AnthropicClient, AuthError, MockLLM
from clearqueue.memory import VendorMemory

ROOT = Path(__file__).parent


def rel(p: Path) -> str:
    """Repo-relative POSIX path.

    Printed paths and recorded paths must not carry an absolute home directory: it leaks a
    username into committed artifacts and onto the screen during a demo, and it makes the
    approval log unreadable on any machine but the one that produced it.
    """
    try:
        return p.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return p.as_posix()


def mock_responder(cases_dir: Path):
    """The mock's scripted policy: approve everything at the billed amount.

    This is deliberately the always-approve control strategy. A mock run must therefore
    score exactly what `score.py --controls` reports for always_approve. If it does not,
    the harness is broken -- which is the only thing a mock run is able to tell us.
    """
    def respond(case_id: str) -> dict:
        inv_path = cases_dir / case_id / "invoice.json"
        if not inv_path.exists():
            return {"case_id": case_id, "disposition": "APPROVE_FOR_PAYMENT",
                    "payable_amount": 0.0, "currency": "USD",
                    "required_approver_role": "AP_CLERK", "defects": [], "citations": [],
                    "rationale": "mock"}
        inv = json.loads(inv_path.read_text(encoding="utf-8"))
        amt = float(inv["gross_amount"])
        role = "AP_CLERK" if amt <= 10000 else ("AP_MANAGER" if amt <= 25000 else "CONTROLLER")
        return {
            "case_id": case_id,
            "disposition": "APPROVE_FOR_PAYMENT",
            "payable_amount": amt,
            "currency": inv["currency"],
            "required_approver_role": role,
            "defects": [],
            "citations": [],
            "rationale": "MOCK LLM: scripted always-approve. Not a decision.",
        }
    return respond


def select_cases(cases_dir: Path, spec: str) -> list[str]:
    all_cases = sorted(p.name for p in cases_dir.iterdir()
                       if p.is_dir() and (p / "invoice.json").exists())
    if spec in ("all", "", None):
        return all_cases
    wanted = [c.strip().upper() for c in spec.split(",") if c.strip()]
    missing = [c for c in wanted if c not in all_cases]
    if missing:
        raise SystemExit(f"unknown cases: {', '.join(missing)}")
    return wanted


def run_version(version, cases: list[str], cases_dir: Path, out_root: Path,
                llm_kind: str, model: str, effort: str, write_packets: bool) -> list[tuple[str, dict]]:
    policy_text = (ROOT / "policy" / "ap_policy.md").read_text(encoding="utf-8")

    if llm_kind == "mock":
        client = MockLLM(responder=mock_responder(cases_dir))
        source = "deterministic mock (no credential, no cost)"
    else:
        client = AnthropicClient(model=model, effort=effort, repo_root=ROOT)
        source = client.credential_source

    out_root.mkdir(parents=True, exist_ok=True)
    memory = VendorMemory(out_root / "memory" / "vendors.jsonl", enabled=version.memory)
    memory.reset()  # a scored run always starts from an empty memory

    results: list[tuple[str, dict]] = []
    started = time.time()
    print(f"\n=== {version.name} — {version.headline}")
    print(f"    levers: {', '.join(version.levers())}")
    print(f"    llm: {llm_kind}" + (f" ({model}, effort={effort})" if llm_kind != "mock" else ""))
    print(f"    credential: {source}")
    print()

    for i, case_id in enumerate(cases, 1):
        case_dir = cases_dir / case_id
        t0 = time.time()
        verdict = solve_case(
            case_id, case_dir, version, client, policy_text,
            out_root / case_id, memory=memory,
        )
        # Cases are processed in queue order so v5's memory accumulates the way a real
        # clerk's would: only from invoices already worked, never from ones still ahead.
        if version.memory:
            from clearqueue.arms import load_case
            memory.observe(case_id, load_case(case_dir), verdict)

        results.append((case_id, verdict))
        amt = verdict.get("payable_amount")
        amt_s = f"{amt:>12,.2f}" if isinstance(amt, (int, float)) else f"{'—':>12}"
        print(f"  [{i:>2}/{len(cases)}] {case_id}  {str(verdict.get('disposition')):<24}"
              f"{amt_s}  {time.time() - t0:>5.1f}s")

    if write_packets:
        packets_dir = ROOT / "out" / "packets"
        packets_dir.mkdir(parents=True, exist_ok=True)
        for case_id, verdict in results:
            text = packet.render(case_id, cases_dir / case_id, verdict, out_root / case_id)
            (packets_dir / f"{case_id}.md").write_text(text, encoding="utf-8")
        packet.queue_report(version, results, ROOT / "out" / "queue_report.md")
        print(f"\n  {len(results)} review packets -> out/packets/")
        print(f"  queue summary          -> out/queue_report.md")

    print(f"\n  wall clock {time.time() - started:.1f}s   traces -> {rel(out_root)}/")
    print(f"  score it:  python score.py --run {rel(out_root)}")
    return results


# --------------------------------------------------------------------------------------
# Human approval gate (ground rules 04 and 05)
# --------------------------------------------------------------------------------------

def review(out_root: Path, cases_dir: Path) -> int:
    """Step a reviewer through the queue. This is the only place a decision is made."""
    verdict_files = sorted(out_root.glob("*/verdict.json"))
    if not verdict_files:
        raise SystemExit(f"no verdicts under {out_root}/ — run a triage pass first")

    decisions_path = out_root / "approvals.jsonl"
    decisions: list[dict] = []
    print(f"\nReview queue: {len(verdict_files)} exceptions awaiting decision.")
    print("ClearQueue has paid nothing. Each item below needs your sign-off.\n")

    # An approval record without a name and a time is not an audit trail. Ask once.
    try:
        reviewer = input("Reviewer name for the approval log > ").strip()
    except EOFError:
        print("\nNo interactive terminal available — review needs a real console.")
        print("Run this in a terminal: python run.py --review")
        return 1
    if not reviewer:
        print("A reviewer name is required; nothing was recorded.")
        return 1

    for vf in verdict_files:
        v = json.loads(vf.read_text(encoding="utf-8"))
        case_id = v.get("case_id", vf.parent.name)
        pkt = ROOT / "out" / "packets" / f"{case_id}.md"
        amt = v.get("payable_amount")
        amt_s = f"{amt:,.2f}" if isinstance(amt, (int, float)) else "n/a"

        print("=" * 78)
        print(f"{case_id}   {v.get('disposition')}   {amt_s} {v.get('currency', '')}")
        print(f"approver required: {v.get('required_approver_role')}")
        if v.get("defects"):
            print(f"defects: {', '.join(v['defects'])}")
        if v.get("citations"):
            print(f"evidence: {', '.join(v['citations'])}")
        print(f"\n{v.get('rationale', '')}\n")
        if pkt.exists():
            print(f"full packet: {rel(pkt)}")
        try:
            choice = input("\n[a]pprove  [r]eject  [e]scalate  [s]kip  [q]uit > ").strip().lower()
        except EOFError:
            print("\n\nNo interactive terminal available — review needs a real console.")
            print("Run this in a terminal: python run.py --review")
            return 1
        if choice.startswith("q"):
            break
        action = {"a": "APPROVED", "r": "REJECTED", "e": "ESCALATED"}.get(choice[:1], "SKIPPED")
        decisions.append({
            "case_id": case_id,
            "recommended": v.get("disposition"),
            "recommended_amount": amt,
            "required_approver_role": v.get("required_approver_role"),
            "human_decision": action,
            "reviewer": reviewer,
            "decided_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "trajectory": rel(vf.parent / "trajectory.jsonl"),
        })
        print(f"  -> {action}\n")

    if decisions:
        # Append. An approval log that overwrites the previous session's decisions is not
        # a log; a second reviewer working the same queue must not erase the first.
        with decisions_path.open("a", encoding="utf-8") as fh:
            for d in decisions:
                fh.write(json.dumps(d) + "\n")
        approved = sum(1 for d in decisions if d["human_decision"] == "APPROVED")
        released = sum(d["recommended_amount"] or 0 for d in decisions
                       if d["human_decision"] == "APPROVED")
        print(f"\n{approved}/{len(decisions)} approved, {released:,.2f} released for payment "
              f"by human decision.")
        print(f"Recorded in {rel(decisions_path)}")
    return 0


# --------------------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", "-v", default="final",
                    help=f"one of: {', '.join(VERSIONS)}")
    ap.add_argument("--ladder", action="store_true",
                    help="run every version in order (v0 through v5)")
    ap.add_argument("--llm", default="mock", choices=["mock", "anthropic"])
    ap.add_argument("--model", default="claude-opus-5")
    ap.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    ap.add_argument("--cases", default="all", help="'all' or a comma-separated list")
    ap.add_argument("--cases-dir", default="cases")
    ap.add_argument("--out", default=None, help="run directory (default runs/<version>)")
    ap.add_argument("--no-packets", action="store_true")
    ap.add_argument("--review", action="store_true", help="human approval gate over a run")
    ap.add_argument("--probe", action="store_true",
                    help="check which API features this credential supports, then stop")
    args = ap.parse_args()

    cases_dir = ROOT / args.cases_dir

    if args.probe:
        from clearqueue.probe import probe
        return probe(model=args.model, repo_root=ROOT)

    if args.review:
        out_root = Path(args.out) if args.out else ROOT / "runs" / "final"
        return review(out_root, cases_dir)

    cases = select_cases(cases_dir, args.cases)
    versions = [VERSIONS[n] for n in LADDER] if args.ladder else [VERSIONS[args.version]]
    if not args.ladder and args.version not in VERSIONS:
        raise SystemExit(f"unknown version '{args.version}'. Choose from: {', '.join(VERSIONS)}")

    try:
        for version in versions:
            out_root = Path(args.out) if args.out else ROOT / "runs" / version.name
            run_version(version, cases, cases_dir, out_root, args.llm, args.model,
                        args.effort, not args.no_packets)
    except AuthError as e:
        print(f"\n{e}\n", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
