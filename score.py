"""Deterministic scorer for ClearQueue.

No LLM is involved in scoring. Every number here is arithmetic over the recorded verdicts
and the hand-authored ground truth in cases/*/expected.json.

Usage
-----
  python score.py --run runs/v0-baseline
  python score.py --compare runs/v0-baseline runs/v5-final
  python score.py --table runs/*            # every run, one row each
  python score.py --controls               # degenerate strategies, no LLM
  python score.py --selftest               # prove the metric is not rigged
  python score.py --replay runs/recorded   # score committed traces, no API key
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

CENT = 0.01
HALF_CENT = 0.005

APPROVE = "APPROVE_FOR_PAYMENT"
DISPOSITIONS = [
    APPROVE,
    "SHORT_PAY",
    "HOLD_PRICE_VARIANCE",
    "HOLD_QUANTITY_VARIANCE",
    "DUPLICATE_REJECT",
    "ESCALATE_HUMAN",
]

# Minutes a human spends per exception. Baseline figure is the manual process this
# project is measured against; see README "Where the 11 minutes comes from".
MANUAL_MINUTES_PER_EXCEPTION = 11.0
# Minutes to review a prepared packet rather than investigate from scratch.
REVIEW_MINUTES_PER_PACKET = 2.5


# --------------------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------------------

def load_truth(cases_dir: Path) -> dict[str, dict]:
    truth = {}
    for exp in sorted(cases_dir.glob("*/expected.json")):
        d = json.loads(exp.read_text(encoding="utf-8"))
        truth[d["case_id"]] = d
    if not truth:
        raise SystemExit(f"No ground truth found under {cases_dir}/. Run build_dataset.py first.")
    return truth


def load_verdicts(run_dir: Path) -> dict[str, dict]:
    verdicts = {}
    for v in sorted(run_dir.glob("*/verdict.json")):
        d = json.loads(v.read_text(encoding="utf-8"))
        cid = d.get("case_id") or v.parent.name
        verdicts[cid] = d
    return verdicts


# --------------------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------------------

def money_eq(a: float, b: float) -> bool:
    """Equal to the cent, which is what the primary metric claims.

    This used to be `abs(...) <= CENT`, which accepted a full one-cent discrepancy and so
    did not mean what the documentation said it meant. It flattered v4-verifier, whose
    CASE-020 answer was a cent under the truth, into scoring as correct. Half a cent is the
    widest tolerance consistent with "rounds to the same cent"; it absorbs float
    representation noise and nothing else.
    """
    return abs(float(a) - float(b)) < HALF_CENT


def score_case(truth: dict, verdict: dict | None) -> dict:
    """Score one case. A missing or unparseable verdict counts as a total miss."""
    if verdict is None:
        return {
            "case_id": truth["case_id"], "produced": False,
            "disposition_ok": False, "amount_ok": False, "resolved": False,
            "approver_ok": False, "citation_ok": False,
            "overpay": 0.0, "underpay": round(float(truth["payable_amount"]), 2),
            "false_approval": False, "predicted": None,
            "true_disposition": truth["disposition"],
        }

    pred_disp = verdict.get("disposition")
    pred_amt = verdict.get("payable_amount")
    try:
        pred_amt = float(pred_amt)
    except (TypeError, ValueError):
        pred_amt = None

    true_disp = truth["disposition"]
    true_amt = round(float(truth["payable_amount"]), 2)

    disposition_ok = pred_disp == true_disp
    amount_ok = pred_amt is not None and money_eq(pred_amt, true_amt)

    # Citations: only assessed where ground truth names decisive evidence.
    required = set(truth.get("must_cite") or [])
    if required:
        cited = {str(c).replace("\\", "/").strip() for c in (verdict.get("citations") or [])}
        # Accept a citation that ends with the required path, so "CASE-005/correspondence/x.txt"
        # satisfies "correspondence/x.txt".
        citation_ok = all(any(c == r or c.endswith("/" + r) for c in cited) for r in required)
    else:
        citation_ok = True

    approver_ok = verdict.get("required_approver_role") == truth.get("required_approver_role")

    # Money exposure. Overpay is the dangerous direction.
    if pred_amt is None:
        overpay, underpay = 0.0, true_amt
    else:
        overpay = max(0.0, round(pred_amt - true_amt, 2))
        underpay = max(0.0, round(true_amt - pred_amt, 2))

    false_approval = pred_disp == APPROVE and true_disp != APPROVE

    return {
        "case_id": truth["case_id"], "produced": True,
        "disposition_ok": disposition_ok, "amount_ok": amount_ok,
        "resolved": disposition_ok and amount_ok,
        "approver_ok": approver_ok, "citation_ok": citation_ok,
        "overpay": overpay, "underpay": underpay,
        "false_approval": false_approval,
        "predicted": pred_disp, "true_disposition": true_disp,
    }


def score_run(truth: dict[str, dict], verdicts: dict[str, dict], label: str) -> dict:
    rows = [score_case(t, verdicts.get(cid)) for cid, t in sorted(truth.items())]
    n = len(rows)
    non_approve = [r for r in rows if r["true_disposition"] != APPROVE]
    cite_cases = [
        r for r in rows
        if truth[r["case_id"]].get("must_cite")
    ]

    produced = sum(r["produced"] for r in rows)
    meta_list = [verdicts[c].get("_meta", {}) for c in verdicts]
    in_tok = sum(m.get("input_tokens", 0) or 0 for m in meta_list)
    out_tok = sum(m.get("output_tokens", 0) or 0 for m in meta_list)
    latency = sum(m.get("latency_s", 0) or 0 for m in meta_list)
    tool_calls = sum(m.get("tool_calls", 0) or 0 for m in meta_list)
    cost = sum(m.get("cost_usd", 0) or 0 for m in meta_list)

    return {
        "label": label,
        "n": n,
        "produced": produced,
        "resolution_accuracy": pct(sum(r["resolved"] for r in rows), n),
        "disposition_accuracy": pct(sum(r["disposition_ok"] for r in rows), n),
        "amount_accuracy": pct(sum(r["amount_ok"] for r in rows), n),
        "approver_accuracy": pct(sum(r["approver_ok"] for r in rows), n),
        "citation_validity": pct(sum(r["citation_ok"] for r in cite_cases), len(cite_cases)),
        "false_approval_rate": pct(sum(r["false_approval"] for r in rows), len(non_approve)),
        "false_approvals": sum(r["false_approval"] for r in rows),
        "non_approve_cases": len(non_approve),
        "overpay_exposure": round(sum(r["overpay"] for r in rows), 2),
        "underpay_exposure": round(sum(r["underpay"] for r in rows), 2),
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "tool_calls": tool_calls,
        "latency_s": round(latency, 1),
        "cost_usd": round(cost, 4),
        "rows": rows,
    }


def pct(num: int, den: int) -> float:
    return round(100.0 * num / den, 1) if den else 0.0


# --------------------------------------------------------------------------------------
# Degenerate controls -- no LLM, to expose how much of a score is free
# --------------------------------------------------------------------------------------

def control_verdicts(truth: dict[str, dict], cases_dir: Path, strategy: str) -> dict[str, dict]:
    out = {}
    for cid in truth:
        inv = json.loads((cases_dir / cid / "invoice.json").read_text(encoding="utf-8"))
        if strategy == "always_approve":
            disp, amt = APPROVE, inv["gross_amount"]
        elif strategy == "always_escalate":
            disp, amt = "ESCALATE_HUMAN", inv["gross_amount"]
        elif strategy == "always_hold":
            disp, amt = "HOLD_PRICE_VARIANCE", 0.00
        else:
            raise ValueError(strategy)
        amt_f = float(amt)
        role = ("AP_CLERK" if amt_f <= 10000 else
                "AP_MANAGER" if amt_f <= 25000 else "CONTROLLER")
        out[cid] = {
            "case_id": cid, "disposition": disp, "payable_amount": amt_f,
            "currency": inv["currency"], "required_approver_role": role,
            "citations": [], "rationale": f"control strategy: {strategy}",
        }
    return out


# --------------------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------------------

HEADERS = [
    ("label", "Run", 26),
    ("resolution_accuracy", "Resolved%", 10),
    ("disposition_accuracy", "Disp%", 7),
    ("amount_accuracy", "Amt%", 7),
    ("false_approval_rate", "FalseAppr%", 11),
    ("overpay_exposure", "Overpay$", 11),
    ("underpay_exposure", "Underpay$", 11),
    ("citation_validity", "Cite%", 7),
]


def print_table(results: list[dict]) -> None:
    head = "".join(h.ljust(w) for _, h, w in HEADERS)
    print(head)
    print("-" * len(head))
    for r in results:
        cells = []
        for key, _, w in HEADERS:
            v = r[key]
            s = f"{v:,.2f}" if key.endswith("exposure") else (f"{v}" if not isinstance(v, float) else f"{v}")
            cells.append(str(s).ljust(w))
        print("".join(cells))


def print_detail(result: dict) -> None:
    print(f"\nPer-case detail for {result['label']}:")
    print(f"{'Case':<11}{'Truth':<24}{'Predicted':<24}{'Res':<5}{'Notes'}")
    print("-" * 88)
    for r in result["rows"]:
        notes = []
        if not r["produced"]:
            notes.append("NO VERDICT")
        if r["false_approval"]:
            notes.append("FALSE APPROVAL")
        if r["produced"] and not r["amount_ok"]:
            if r["overpay"]:
                notes.append(f"overpay ${r['overpay']:,.2f}")
            if r["underpay"]:
                notes.append(f"underpay ${r['underpay']:,.2f}")
        if not r["citation_ok"]:
            notes.append("missed citation")
        mark = "OK " if r["resolved"] else "-- "
        print(
            f"{r['case_id']:<11}{r['true_disposition']:<24}"
            f"{str(r['predicted']):<24}{mark:<5}{', '.join(notes)}"
        )


def print_summary(result: dict) -> None:
    r = result
    saved = r["n"] * (MANUAL_MINUTES_PER_EXCEPTION - REVIEW_MINUTES_PER_PACKET)
    print(f"\n{r['label']}")
    print(f"  cases                 {r['n']} ({r['produced']} produced a verdict)")
    print(f"  resolution accuracy   {r['resolution_accuracy']}%   (disposition AND amount to the cent)")
    print(f"  disposition accuracy  {r['disposition_accuracy']}%")
    print(f"  amount accuracy       {r['amount_accuracy']}%")
    print(f"  approver accuracy     {r['approver_accuracy']}%")
    print(f"  citation validity     {r['citation_validity']}%")
    print(f"  false approvals       {r['false_approvals']}/{r['non_approve_cases']} = {r['false_approval_rate']}%")
    print(f"  overpayment exposure  ${r['overpay_exposure']:,.2f}")
    print(f"  underpayment exposure ${r['underpay_exposure']:,.2f}")
    if r["input_tokens"] or r["output_tokens"]:
        print(f"  tokens                {r['input_tokens']:,} in / {r['output_tokens']:,} out")
    if r["tool_calls"]:
        print(f"  tool calls            {r['tool_calls']}")
    if r["cost_usd"]:
        print(f"  cost                  ${r['cost_usd']:.4f}  (${r['cost_usd']/r['n']:.4f}/case)")
    if r["latency_s"]:
        print(f"  wall clock            {r['latency_s']}s")
    print(f"  human minutes saved   {saved:.0f} min across {r['n']} exceptions "
          f"({MANUAL_MINUTES_PER_EXCEPTION} -> {REVIEW_MINUTES_PER_PACKET} min each)")


# --------------------------------------------------------------------------------------
# Self-test -- proves the scorer rewards correctness and punishes the dangerous error
# --------------------------------------------------------------------------------------

def selftest(cases_dir: Path) -> int:
    truth = load_truth(cases_dir)
    failures = []

    def expect(name: str, got, want):
        if got != want:
            failures.append(f"{name}: got {got}, expected {want}")

    # 1. A perfect run scores 100 on everything and zero exposure.
    perfect = {
        cid: {
            "case_id": cid,
            "disposition": t["disposition"],
            "payable_amount": t["payable_amount"],
            "currency": t["currency"],
            "required_approver_role": t["required_approver_role"],
            "citations": list(t.get("must_cite") or []),
        }
        for cid, t in truth.items()
    }
    r = score_run(truth, perfect, "selftest/perfect")
    expect("perfect resolution", r["resolution_accuracy"], 100.0)
    expect("perfect citations", r["citation_validity"], 100.0)
    expect("perfect false approvals", r["false_approvals"], 0)
    expect("perfect overpay", r["overpay_exposure"], 0.0)

    # 2. ONE cent off must fail the amount check but keep the disposition.
    #    This test previously used two cents, which meant it passed against a scorer that
    #    tolerated a full cent -- it was written around the bug instead of catching it.
    onecent = json.loads(json.dumps(perfect))
    target = "CASE-001"
    onecent[target]["payable_amount"] = truth[target]["payable_amount"] + 0.01
    r = score_run(truth, onecent, "selftest/onecent")
    expect("1c off disposition still 100", r["disposition_accuracy"], 100.0)
    expect("1c off resolution drops", r["resolution_accuracy"] < 100.0, True)
    expect("1c off overpay recorded", round(r["overpay_exposure"], 2), 0.01)

    # 3. Approving everything must produce the maximum false-approval rate.
    always = control_verdicts(truth, cases_dir, "always_approve")
    r = score_run(truth, always, "selftest/always_approve")
    expect("always-approve false approval rate", r["false_approval_rate"], 100.0)
    expect("always-approve overpays", r["overpay_exposure"] > 0, True)

    # 4. A missing verdict must not silently pass.
    missing = json.loads(json.dumps(perfect))
    missing.pop("CASE-014")
    r = score_run(truth, missing, "selftest/missing")
    expect("missing verdict counts as unresolved", r["produced"], len(truth) - 1)
    expect("missing verdict resolution < 100", r["resolution_accuracy"] < 100.0, True)

    # 5. Refusing to pay anything must show as underpayment, not as a win.
    hold = control_verdicts(truth, cases_dir, "always_hold")
    r = score_run(truth, hold, "selftest/always_hold")
    expect("always-hold has no false approvals", r["false_approvals"], 0)
    expect("always-hold underpays heavily", r["underpay_exposure"] > 50000, True)

    if failures:
        print("SELFTEST FAILED:")
        for f in failures:
            print("  -", f)
        return 1
    print("Scorer selftest passed (5 checks).")
    print("  - a perfect run scores 100% with zero exposure")
    print("  - a one-cent error fails the amount check but not the disposition check")
    print("  - approving everything yields a 100% false-approval rate")
    print("  - a missing verdict is counted as unresolved, never skipped")
    print("  - holding everything shows as underpayment, so caution is not free")
    return 0


# --------------------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Score ClearQueue runs against ground truth.")
    ap.add_argument("--cases", default="cases", help="cases directory")
    ap.add_argument("--run", help="score a single run directory")
    ap.add_argument("--compare", nargs="+", help="compare two or more run directories")
    ap.add_argument("--table", nargs="+", help="one row per run directory")
    ap.add_argument("--replay", help="score committed traces without any API key")
    ap.add_argument("--controls", action="store_true", help="score degenerate strategies")
    ap.add_argument("--selftest", action="store_true", help="validate the scorer itself")
    ap.add_argument("--detail", action="store_true", help="print per-case detail")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    args = ap.parse_args()

    cases_dir = Path(args.cases)

    if args.selftest:
        return selftest(cases_dir)

    truth = load_truth(cases_dir)

    def build(run_path: str) -> dict:
        p = Path(run_path)
        v = load_verdicts(p)
        if not v:
            print(f"warning: no verdicts under {p}/", file=sys.stderr)
        return score_run(truth, v, p.name)

    results: list[dict] = []

    if args.controls:
        for strat in ("always_approve", "always_hold", "always_escalate"):
            results.append(score_run(truth, control_verdicts(truth, cases_dir, strat), f"control/{strat}"))

    targets: list[str] = []
    for opt in (args.run, args.replay):
        if opt:
            targets.append(opt)
    for opt in (args.compare, args.table):
        if opt:
            for pattern in opt:
                expanded = sorted(glob.glob(pattern))
                targets.extend(expanded if expanded else [pattern])

    for t in targets:
        results.append(build(t))

    if not results:
        ap.print_help()
        return 2

    if args.json:
        print(json.dumps([{k: v for k, v in r.items() if k != "rows"} for r in results], indent=2))
        return 0

    if len(results) == 1 and not args.controls:
        print_summary(results[0])
        if args.detail:
            print_detail(results[0])
    else:
        print_table(results)
        if args.detail:
            for r in results:
                print_detail(r)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
