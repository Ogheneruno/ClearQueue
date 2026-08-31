"""Deterministic calculators exposed to the agent as tools.

Design rule, and it is the whole point of this file: **these tools compute, they never
decide.** Each one implements a single mechanical clause of `policy/ap_policy.md` -- unit
conversion, the tolerance band, tax recomputation, the approval threshold. None of them
returns a disposition.

The judgment that the exception queue actually needs -- is this authorisation genuine, is
this a duplicate or a monthly retainer, does this contract clause cover this freight charge
-- stays with the model. The arithmetic that models are quietly bad at, and that must be
right to the cent, moves into code that is unit-testable and never has an off day.

Every call is recorded, so the review packet can show a human exactly which numbers were
derived mechanically and which were a judgment call.
"""

from __future__ import annotations

import json
import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

# Legal-entity suffixes stripped before comparing vendor names (policy clause 8.1).
NAME_SUFFIXES = {
    "LTD", "LLC", "INC", "CO", "COMPANY", "CORP", "GMBH", "PLC", "LIMITED",
}

PRICE_TOLERANCE_PCT = 0.02      # clause 3
PRICE_TOLERANCE_CAP = 50.00     # clause 3
OVER_DELIVERY_TOLERANCE = 0.05  # clause 4
TAX_ROUNDING_ALLOWANCE = 0.02   # clause 5
FREIGHT_CAP = 500.00            # clause 6
DUPLICATE_WINDOW_DAYS = 45      # clause 8
DUPLICATE_AMOUNT_EPSILON = 0.01  # clause 8


def money(x: float | str | Decimal) -> float:
    """Round to cents, half-up.

    Python's built-in round() is banker's rounding: round(2.675, 2) is 2.67, not 2.68.
    On an invoice that is a defect, so all money passes through here.
    """
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def normalize_vendor_name(name: str) -> str:
    """Clause 8.1: fold case, punctuation and legal-entity suffixes."""
    cleaned = re.sub(r"[^A-Za-z0-9 ]+", " ", str(name or "")).upper()
    words = [w for w in cleaned.split() if w and w not in NAME_SUFFIXES]
    return " ".join(words)


def approver_for(net_payable: float) -> str:
    """Clause 10, applied to the final net payable."""
    amt = money(net_payable)
    if amt <= 10000.00:
        return "AP_CLERK"
    if amt <= 25000.00:
        return "AP_MANAGER"
    return "CONTROLLER"


# --------------------------------------------------------------------------------------
# Tool implementations
# --------------------------------------------------------------------------------------

def uom_convert(quantity: float, unit_price: float, factor: float) -> dict:
    """Clause 2. Convert a quantity and its unit price into the PO's unit of measure.

    `factor` is how many target units make up one source unit: converting CASE -> EACH at
    a pack size of 12 means factor=12. Price moves inversely so the line total is
    unchanged -- that invariant is returned so the caller can see it held.
    """
    q, p, f = float(quantity), float(unit_price), float(factor)
    if f <= 0:
        raise ValueError("factor must be positive")
    converted_qty = q * f
    converted_price = p / f
    return {
        "converted_quantity": converted_qty,
        "converted_unit_price": money(converted_price),
        "line_total_before": money(q * p),
        "line_total_after": money(converted_qty * (p / f)),
        "note": "Line total is unchanged by a correct conversion; if the two differ, the "
                "pack size is wrong.",
    }


def apply_tolerance(po_unit_price: float, invoice_unit_price: float) -> dict:
    """Clause 3. Both prices must already be in the same unit of measure.

    The band is the LOWER of 2% and $50.00 per line -- easy to get backwards, which is
    exactly why it lives here rather than in a prompt.
    """
    po_p, inv_p = float(po_unit_price), float(invoice_unit_price)
    pct_allowance = abs(po_p) * PRICE_TOLERANCE_PCT
    allowance = min(pct_allowance, PRICE_TOLERANCE_CAP)
    variance = inv_p - po_p
    within = variance <= allowance + 1e-9
    return {
        "po_unit_price": money(po_p),
        "invoice_unit_price": money(inv_p),
        "variance": money(variance),
        "variance_pct": round(100.0 * variance / po_p, 4) if po_p else None,
        "pct_allowance": money(pct_allowance),
        "cap_allowance": money(PRICE_TOLERANCE_CAP),
        "allowance_applied": money(allowance),
        "within_tolerance": bool(within),
        "note": "Tolerance is the LOWER of 2% of the PO unit price and $50.00 per line "
                "(clause 3). Outside tolerance is a defect unless cured under clause 3.1 "
                "by authorisation from a listed buyer -- that judgment is yours, not this "
                "tool's.",
    }


def check_quantity(po_quantity: float, received_quantity: float, invoiced_quantity: float) -> dict:
    """Clause 4. All three quantities must already be in the PO's unit of measure."""
    po_q, rec_q, inv_q = float(po_quantity), float(received_quantity), float(invoiced_quantity)
    over_allowance = po_q * OVER_DELIVERY_TOLERANCE
    under_delivery = rec_q < inv_q - 1e-9
    over_delivery = rec_q > po_q + 1e-9
    over_beyond_tolerance = rec_q > po_q + over_allowance + 1e-9
    return {
        "po_quantity": po_q,
        "received_quantity": rec_q,
        "invoiced_quantity": inv_q,
        "payable_quantity": min(rec_q, inv_q) if under_delivery else rec_q,
        "under_delivery": under_delivery,
        "over_delivery": over_delivery,
        "over_delivery_pct": round(100.0 * (rec_q - po_q) / po_q, 4) if po_q else None,
        "over_tolerance_quantity": over_allowance,
        "over_delivery_beyond_tolerance": over_beyond_tolerance,
        "note": "Never pay for goods not received: quantity disputes resolve in favour of "
                "the receipt (clause 4). Under-delivery is a defect (SHORT_PAY on received). "
                "Over-delivery within 5% is not a defect; beyond 5% is.",
    }


def recompute_tax(net_amount: float, tax_rate: float, supplier_tax_amount: float | None = None) -> dict:
    """Clause 5. Recompute tax from the vendor's rate on the corrected net; never trust the invoice."""
    net, rate = float(net_amount), float(tax_rate)
    correct_tax = money(net * rate)
    out: dict[str, Any] = {
        "net_amount": money(net),
        "tax_rate": rate,
        "correct_tax": correct_tax,
        "correct_gross": money(net + correct_tax),
    }
    if supplier_tax_amount is not None:
        supplied = float(supplier_tax_amount)
        delta = money(supplied - correct_tax)
        out.update({
            "supplier_tax": money(supplied),
            "delta": delta,
            "within_rounding_allowance": abs(delta) <= TAX_ROUNDING_ALLOWANCE + 1e-9,
            "direction": "overcharged" if delta > 0 else ("undercharged" if delta < 0 else "exact"),
            "note": "Within $0.02 is rounding, not a defect. Overcharge -> SHORT_PAY the "
                    "corrected total. Undercharge -> pay the higher correct total, and it is "
                    "still a defect (tax-compliance exposure).",
        })
    return out


def fx_convert(amount: float, rate: float, from_currency: str = "", to_currency: str = "") -> dict:
    """Clause 7. Apply a contract-fixed rate only. If no contract rate exists, do not call this."""
    converted = money(float(amount) * float(rate))
    return {
        "amount": money(amount),
        "rate": float(rate),
        "from_currency": from_currency,
        "to_currency": to_currency,
        "converted_amount": converted,
        "note": "Only a rate fixed by contract may be used. With no contract rate the case "
                "is ESCALATE_HUMAN (clause 7) -- do not substitute a market rate. The "
                "payable is always expressed in the INVOICE currency.",
    }


def net_credit_memos(payable_amount: float, credit_memos: list | None = None) -> dict:
    """Clause 9. Net open credit memos before the clause-10 threshold is applied."""
    memos = credit_memos or []
    total = 0.0
    applied = []
    for m in memos:
        amt = float(m.get("amount", m) if isinstance(m, dict) else m)
        total += amt
        applied.append({"memo": m.get("memo_id") if isinstance(m, dict) else str(m), "amount": money(amt)})
    gross = float(payable_amount)
    netted = max(0.0, money(gross - total))
    return {
        "payable_before_credits": money(gross),
        "credits_applied": applied,
        "total_credits": money(total),
        "payable_after_credits": netted,
        "floored_at_zero": netted == 0.0 and gross - total < 0,
        "required_approver_role": approver_for(netted),
        "note": "Credits net BEFORE the approval threshold is read (clauses 9, 10). "
                "The payable floors at $0.00 and is never negative.",
    }


def approval_threshold(net_payable: float) -> dict:
    """Clause 10."""
    return {
        "net_payable": money(net_payable),
        "required_approver_role": approver_for(net_payable),
        "bands": {
            "AP_CLERK": "$0.00 - $10,000.00",
            "AP_MANAGER": "$10,000.01 - $25,000.00",
            "CONTROLLER": "above $25,000.00",
        },
        "note": "Above $25,000.00 clause 11 also forces ESCALATE_HUMAN.",
    }


def compare_vendor_names(name_a: str, name_b: str) -> dict:
    """Clause 8.1 name normalisation, in isolation from the duplicate decision itself."""
    na, nb = normalize_vendor_name(name_a), normalize_vendor_name(name_b)
    return {
        "name_a": name_a, "name_b": name_b,
        "normalized_a": na, "normalized_b": nb,
        "same_entity": na == nb,
        "note": "Name match is only one of the five conditions in clause 8. A name match "
                "alone is NOT a duplicate.",
    }


def duplicate_check(
    vendor_name_a: str,
    vendor_name_b: str,
    po_a: str,
    po_b: str,
    gross_a: float,
    gross_b: float,
    date_a: str,
    date_b: str,
    service_period_a: str | None = None,
    service_period_b: str | None = None,
) -> dict:
    """Clause 8, evaluated as the conjunction it actually is.

    Returns each condition separately rather than a verdict, because clause 8.1 -- distinct
    service periods make this a legitimate recurring charge -- is the trap in this queue and
    the model should have to look at it.
    """
    same_vendor = normalize_vendor_name(vendor_name_a) == normalize_vendor_name(vendor_name_b)
    same_po = str(po_a).strip().upper() == str(po_b).strip().upper()
    amount_match = abs(float(gross_a) - float(gross_b)) <= DUPLICATE_AMOUNT_EPSILON
    days = _days_between(date_a, date_b)
    within_window = days is not None and days <= DUPLICATE_WINDOW_DAYS

    sp_a = (service_period_a or "").strip()
    sp_b = (service_period_b or "").strip()
    distinguishing_period = bool(sp_a and sp_b and sp_a != sp_b)

    conditions = {
        "same_vendor_after_normalisation": same_vendor,
        "same_po": same_po,
        "gross_within_one_cent": amount_match,
        "dates_within_45_days": within_window,
        "no_distinguishing_service_period": not distinguishing_period,
    }
    return {
        "conditions": conditions,
        "days_apart": days,
        "service_period_a": sp_a or None,
        "service_period_b": sp_b or None,
        "all_conditions_met": all(conditions.values()),
        "note": "A duplicate requires ALL five conditions (clause 8). Distinct, "
                "non-overlapping service periods make this a legitimate recurring charge "
                "(clause 8.1) -- rejecting one is treated as seriously as an overpayment.",
    }


def _days_between(a: str, b: str) -> int | None:
    from datetime import date
    try:
        da = date.fromisoformat(str(a)[:10])
        db = date.fromisoformat(str(b)[:10])
    except ValueError:
        return None
    return abs((da - db).days)


def line_total(quantity: float, unit_price: float) -> dict:
    """Exact line arithmetic with half-up cent rounding."""
    total = money(float(quantity) * float(unit_price))
    return {"quantity": float(quantity), "unit_price": money(unit_price), "line_total": total}


# --------------------------------------------------------------------------------------
# The toolbox: dispatch, evidence access, and the citation ledger
# --------------------------------------------------------------------------------------

CALCULATORS = {
    "uom_convert": uom_convert,
    "apply_tolerance": apply_tolerance,
    "check_quantity": check_quantity,
    "recompute_tax": recompute_tax,
    "fx_convert": fx_convert,
    "net_credit_memos": net_credit_memos,
    "approval_threshold": approval_threshold,
    "compare_vendor_names": compare_vendor_names,
    "duplicate_check": duplicate_check,
    "line_total": line_total,
}


class ToolBox:
    """Dispatches tool calls for one case and keeps the ledger the packet is built from."""

    def __init__(self, case_dir: Path, memory=None):
        self.case_dir = Path(case_dir)
        self.memory = memory
        self.calls: list[dict] = []
        self.cited: list[str] = []

    # -- evidence ----------------------------------------------------------------------

    def list_evidence(self) -> dict:
        files = []
        for p in sorted(self.case_dir.rglob("*")):
            if p.is_file() and p.name != "expected.json":  # ground truth is never readable
                files.append(p.relative_to(self.case_dir).as_posix())
        return {"files": files}

    def read_evidence(self, path: str) -> dict:
        rel = str(path).replace("\\", "/").strip().lstrip("/")
        target = (self.case_dir / rel).resolve()
        case_root = self.case_dir.resolve()
        if not str(target).startswith(str(case_root)):
            raise ValueError(f"path escapes the case directory: {path}")
        if target.name == "expected.json":
            raise ValueError("expected.json is ground truth and is not readable by an agent")
        if not target.is_file():
            available = self.list_evidence()["files"]
            raise FileNotFoundError(f"no such evidence file: {rel}. Available: {available}")
        if rel not in self.cited:
            self.cited.append(rel)
        return {"path": rel, "content": target.read_text(encoding="utf-8")}

    # -- dispatch ----------------------------------------------------------------------

    def dispatch(self, name: str, args: dict) -> Any:
        if name == "read_evidence":
            result = self.read_evidence(args.get("path", ""))
        elif name == "list_evidence":
            result = self.list_evidence()
        elif name == "recall_vendor":
            if self.memory is None:
                raise ValueError("vendor memory is not enabled for this run")
            result = self.memory.recall(args.get("vendor_name", ""))
        elif name in CALCULATORS:
            result = CALCULATORS[name](**args)
        else:
            raise ValueError(f"unknown tool: {name}")
        self.calls.append({"tool": name, "input": args, "output": result})
        return result


# --------------------------------------------------------------------------------------
# Tool schemas, grouped so each iteration can hand the model a different set
# --------------------------------------------------------------------------------------

def _t(name: str, description: str, props: dict, required: list[str]) -> dict:
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": props,
            "required": required,
            "additionalProperties": False,
        },
    }


NUM = {"type": "number"}
STR = {"type": "string"}

CALC_SCHEMAS = [
    _t("line_total", "Multiply quantity by unit price with correct half-up cent rounding.",
       {"quantity": NUM, "unit_price": NUM}, ["quantity", "unit_price"]),
    _t("uom_convert",
       "Policy clause 2. Convert a quantity and its unit price into the PO's unit of "
       "measure. 'factor' is how many target units are in one source unit (CASE->EACH at "
       "pack size 12 is factor 12). Returns the line total before and after so you can "
       "confirm it is unchanged.",
       {"quantity": NUM, "unit_price": NUM, "factor": NUM},
       ["quantity", "unit_price", "factor"]),
    _t("apply_tolerance",
       "Policy clause 3. Test an invoiced unit price against the PO unit price. Both must "
       "already be in the same unit of measure. Returns whether the variance sits inside "
       "the allowed band (the LOWER of 2% and $50.00).",
       {"po_unit_price": NUM, "invoice_unit_price": NUM},
       ["po_unit_price", "invoice_unit_price"]),
    _t("check_quantity",
       "Policy clause 4. Compare ordered, received and invoiced quantities (all in the PO's "
       "unit of measure) and report under-delivery, over-delivery and the 5% band.",
       {"po_quantity": NUM, "received_quantity": NUM, "invoiced_quantity": NUM},
       ["po_quantity", "received_quantity", "invoiced_quantity"]),
    _t("recompute_tax",
       "Policy clause 5. Recompute tax from the vendor's tax_rate on the corrected net "
       "amount and compare it to the supplier's figure.",
       {"net_amount": NUM, "tax_rate": NUM, "supplier_tax_amount": NUM},
       ["net_amount", "tax_rate"]),
    _t("fx_convert",
       "Policy clause 7. Apply a contract-fixed exchange rate. Do not call this if no "
       "contract rate exists -- that case escalates instead.",
       {"amount": NUM, "rate": NUM, "from_currency": STR, "to_currency": STR},
       ["amount", "rate"]),
    _t("net_credit_memos",
       "Policy clause 9. Net open credit memos against the payable before reading the "
       "approval threshold. Pass credit_memos as a list of {memo_id, amount} objects.",
       {"payable_amount": NUM,
        "credit_memos": {"type": "array", "items": {"type": "object"}}},
       ["payable_amount"]),
    _t("approval_threshold",
       "Policy clause 10. Map a final net payable to the required approver role.",
       {"net_payable": NUM}, ["net_payable"]),
    _t("compare_vendor_names",
       "Policy clause 8.1 name normalisation. Folds case, punctuation and legal-entity "
       "suffixes. A name match alone is not a duplicate.",
       {"name_a": STR, "name_b": STR}, ["name_a", "name_b"]),
    _t("duplicate_check",
       "Policy clause 8. Evaluate all five duplicate conditions against a prior invoice and "
       "return each one separately. Pass service periods when the invoices carry them.",
       {"vendor_name_a": STR, "vendor_name_b": STR, "po_a": STR, "po_b": STR,
        "gross_a": NUM, "gross_b": NUM, "date_a": STR, "date_b": STR,
        "service_period_a": STR, "service_period_b": STR},
       ["vendor_name_a", "vendor_name_b", "po_a", "po_b", "gross_a", "gross_b",
        "date_a", "date_b"]),
]

EVIDENCE_SCHEMAS = [
    _t("list_evidence", "List every evidence file available for this case.", {}, []),
    _t("read_evidence",
       "Read one evidence file for this case by relative path (for example "
       "'correspondence/surcharge_approval.txt' or 'contract.md'). Anything you rely on "
       "must be read through this tool and then cited.",
       {"path": STR}, ["path"]),
]

MEMORY_SCHEMAS = [
    _t("recall_vendor",
       "Recall what earlier invoices in this queue established about a vendor: pack sizes, "
       "known recurring-charge patterns, prior authorisations and past dispositions.",
       {"vendor_name": STR}, ["vendor_name"]),
]


def schemas_for(*groups: str) -> list[dict]:
    out: list[dict] = []
    for g in groups:
        out.extend({"calc": CALC_SCHEMAS, "evidence": EVIDENCE_SCHEMAS, "memory": MEMORY_SCHEMAS}[g])
    return out


# --------------------------------------------------------------------------------------
# Self-test: the calculators must be right, or every number downstream is wrong
# --------------------------------------------------------------------------------------

def selftest() -> int:
    failures = []
    checks = 0

    def check(name, got, want):
        nonlocal checks
        checks += 1
        if got != want:
            failures.append(f"{name}: got {got!r}, expected {want!r}")

    # Half-up money rounding, where the stdlib disagrees with an accountant.
    check("money half-up", money(2.675), 2.68)
    check("money half-up neg", money(-2.675), -2.68)

    # Clause 2: converting CASE->EACH must preserve the line total.
    r = uom_convert(40, 24.00, 12)
    check("uom qty", r["converted_quantity"], 480.0)
    check("uom price", r["converted_unit_price"], 2.00)
    check("uom total preserved", r["line_total_before"], r["line_total_after"])

    # Clause 3: the band is the LOWER of 2% and $50, so a cheap line is capped by the
    # percentage and an expensive line by the $50.
    r = apply_tolerance(62.00, 63.10)          # 1.77% of 62 -> inside
    check("tolerance inside", r["within_tolerance"], True)
    check("tolerance allowance is pct", r["allowance_applied"], 1.24)
    r = apply_tolerance(145.00, 154.00)        # 6.2% -> outside
    check("tolerance outside", r["within_tolerance"], False)
    r = apply_tolerance(5000.00, 5060.00)      # 1.2%, but 2% = $100 > $50 cap
    check("tolerance capped at 50", r["allowance_applied"], 50.00)
    check("tolerance cap bites", r["within_tolerance"], False)

    # Clause 4.
    r = check_quantity(100, 60, 100)
    check("under-delivery", r["under_delivery"], True)
    check("payable qty is received", r["payable_quantity"], 60.0)
    r = check_quantity(100, 118, 118)
    check("over beyond tolerance", r["over_delivery_beyond_tolerance"], True)
    r = check_quantity(100, 104, 104)
    check("over within tolerance", r["over_delivery_beyond_tolerance"], False)

    # Clause 5.
    r = recompute_tax(31500.00, 0.075, 2835.00)
    check("tax correct", r["correct_tax"], 2362.50)
    check("tax overcharged", r["direction"], "overcharged")
    check("tax outside rounding", r["within_rounding_allowance"], False)
    r = recompute_tax(1000.00, 0.075, 75.01)
    check("tax rounding tolerated", r["within_rounding_allowance"], True)

    # Clause 8.1: the recurring-charge trap must not read as a duplicate.
    r = duplicate_check("Nordwind Logistics Ltd", "NORDWIND LOGISTICS, LLC",
                        "PO-4407", "PO-4407", 3225.00, 3225.00, "2026-03-04", "2026-02-13")
    check("duplicate detected", r["all_conditions_met"], True)
    r = duplicate_check("Halcyon Services", "Halcyon Services",
                        "PO-4408", "PO-4408", 5160.00, 5160.00, "2026-03-01", "2026-02-01",
                        "2026-03-01/2026-03-31", "2026-02-01/2026-02-28")
    check("recurring not duplicate", r["all_conditions_met"], False)
    check("recurring reason", r["conditions"]["no_distinguishing_service_period"], False)

    # Clauses 9 and 10, including the boundary the threshold table hinges on.
    r = net_credit_memos(33862.50, [{"memo_id": "CM-2026-014", "amount": 1500.00}])
    check("credit netting", r["payable_after_credits"], 32362.50)
    check("credit approver", r["required_approver_role"], "CONTROLLER")
    check("approver at 10000", approver_for(10000.00), "AP_CLERK")
    check("approver just over 10000", approver_for(10000.01), "AP_MANAGER")
    check("approver at 25000", approver_for(25000.00), "AP_MANAGER")
    check("approver just over 25000", approver_for(25000.01), "CONTROLLER")
    r = net_credit_memos(100.00, [{"memo_id": "CM-X", "amount": 500.00}])
    check("credit floors at zero", r["payable_after_credits"], 0.0)

    # Clause 7.
    check("fx", fx_convert(9030.00, 1.10)["converted_amount"], 9933.00)

    if failures:
        print("TOOLS SELFTEST FAILED:")
        for f in failures:
            print("  -", f)
        return 1
    print(f"Tools selftest passed ({checks} checks).")
    print("  - money rounds half-up, not banker's (2.675 -> 2.68)")
    print("  - UOM conversion preserves the line total")
    print("  - the price band is the LOWER of 2% and $50.00, and the cap really bites")
    print("  - under-delivery pays on the receipt; over-delivery honours the 5% band")
    print("  - tax is recomputed from the vendor rate, with the $0.02 rounding allowance")
    print("  - a distinct service period stops the recurring charge reading as a duplicate")
    print("  - credits net before the threshold, floor at $0.00, and move the approver")
    return 0


if __name__ == "__main__":
    raise SystemExit(selftest())
