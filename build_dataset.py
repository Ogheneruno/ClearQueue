"""Generate the ClearQueue evaluation dataset.

Every case is declared here so the dataset is reproducible from source. Ground-truth
figures are hand-derived literals -- deliberately NOT computed by this script, so that a
bug in the harness cannot quietly move the target. The assertions at the bottom check
*internal consistency* of the documents (line amounts sum to the net, net + tax = gross as
billed) which catches typos without re-deriving the answer.

Usage:  python build_dataset.py [--out cases]
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

# --------------------------------------------------------------------------------------
# Vendors
# --------------------------------------------------------------------------------------

VENDORS = {
    "meridian": {
        "vendor_id": "V-1001",
        "name": "Meridian Paper Co",
        "tax_rate": 0.075,
        "tax_jurisdiction": "State sales tax, 7.5%",
        "currency": "USD",
        "payment_terms": "2/10 NET 30",
        "pack_sizes": {},
        "authorised_buyers": ["Dele Fashanu", "Priya Raman"],
        "prior_invoices": [],
        "open_credit_memos": [],
    },
    "kestrel": {
        "vendor_id": "V-1002",
        "name": "Kestrel Industrial Supply",
        "tax_rate": 0.075,
        "tax_jurisdiction": "State sales tax, 7.5%",
        "currency": "USD",
        "payment_terms": "2/10 NET 30",
        "pack_sizes": {"CASE": 12},
        "authorised_buyers": ["Dele Fashanu", "Priya Raman"],
        "prior_invoices": [],
        "open_credit_memos": [],
    },
    "nordwind": {
        "vendor_id": "V-1003",
        "name": "Nordwind Supply Company LLC",
        "tax_rate": 0.075,
        "tax_jurisdiction": "State sales tax, 7.5%",
        "currency": "USD",
        "payment_terms": "NET 30",
        "pack_sizes": {},
        "authorised_buyers": ["Priya Raman"],
        "prior_invoices": [],
        "open_credit_memos": [],
    },
    "halcyon": {
        "vendor_id": "V-1004",
        "name": "Halcyon Facilities Management Ltd",
        "tax_rate": 0.075,
        "tax_jurisdiction": "State sales tax, 7.5%",
        "currency": "USD",
        "payment_terms": "NET 30",
        "pack_sizes": {},
        "authorised_buyers": ["Dele Fashanu"],
        "prior_invoices": [],
        "open_credit_memos": [],
    },
    "rheinwerk": {
        "vendor_id": "V-1005",
        "name": "Rheinwerk Komponenten GmbH",
        "tax_rate": 0.075,
        "tax_jurisdiction": "State sales tax, 7.5%",
        "currency": "EUR",
        "payment_terms": "NET 45",
        "pack_sizes": {},
        "authorised_buyers": ["Priya Raman"],
        "prior_invoices": [],
        "open_credit_memos": [],
    },
    "ashgrove": {
        "vendor_id": "V-1006",
        "name": "Ashgrove Legal Partners",
        "tax_rate": 0.075,
        "tax_jurisdiction": "State sales tax, 7.5%",
        "currency": "USD",
        "payment_terms": "NET 30",
        "pack_sizes": {},
        "authorised_buyers": ["Dele Fashanu"],
        "prior_invoices": [],
        "open_credit_memos": [],
    },
}


def vendor(key: str, **overrides: object) -> dict:
    v = json.loads(json.dumps(VENDORS[key]))
    v.update(overrides)
    return v


def line(n: int, desc: str, qty: float, uom: str, price: float, amount: float) -> dict:
    return {
        "line": n,
        "description": desc,
        "quantity": qty,
        "uom": uom,
        "unit_price": price,
        "amount": amount,
    }


# --------------------------------------------------------------------------------------
# Cases
# --------------------------------------------------------------------------------------

CASES: list[dict] = [
    # ---------------------------------------------------------------- 001 clean control
    {
        "id": "CASE-001",
        "title": "Clean three-way match",
        "tests": "Control. Punishes an agent that invents problems.",
        "vendor": vendor("meridian"),
        "po": {
            "po_number": "PO-4401", "type": "GOODS", "currency": "USD",
            "buyer": "Dele Fashanu", "po_date": "2026-02-20",
            "lines": [line(1, "A4 Copy Paper, 500-sheet ream", 200, "EACH", 4.20, 840.00)],
        },
        "receipt": {
            "receipt_number": "GR-7701", "po_number": "PO-4401",
            "received_date": "2026-03-04",
            "lines": [{"line": 1, "quantity": 200, "uom": "EACH"}],
        },
        "invoice": {
            "invoice_number": "INV-88120", "vendor_name_as_billed": "Meridian Paper Co",
            "po_number": "PO-4401", "invoice_date": "2026-03-06", "currency": "USD",
            "service_period": None,
            "lines": [line(1, "A4 Copy Paper, 500-sheet ream", 200, "EACH", 4.20, 840.00)],
            "net_amount": 840.00, "tax_amount": 63.00, "gross_amount": 903.00,
        },
        "expected": {
            "disposition": "APPROVE_FOR_PAYMENT", "payable_amount": 903.00,
            "currency": "USD", "required_approver_role": "AP_CLERK",
            "must_cite": [], "defects": [],
            "rationale_key_facts": [
                "PO, receipt and invoice agree on 200 EACH at $4.20.",
                "Tax of $63.00 equals 7.5% of $840.00.",
            ],
        },
    },
    # ---------------------------------------------------------------- 002 UOM mismatch
    {
        "id": "CASE-002",
        "title": "Unit-of-measure mismatch (CASE vs EACH)",
        "tests": "Normalisation is not a defect.",
        "vendor": vendor("kestrel"),
        "po": {
            "po_number": "PO-4402", "type": "GOODS", "currency": "USD",
            "buyer": "Priya Raman", "po_date": "2026-02-18",
            "lines": [line(1, "Nitrile Gloves, 12 per case", 40, "CASE", 24.00, 960.00)],
        },
        "receipt": {
            "receipt_number": "GR-7702", "po_number": "PO-4402",
            "received_date": "2026-03-02",
            "lines": [{"line": 1, "quantity": 40, "uom": "CASE"}],
        },
        "invoice": {
            "invoice_number": "INV-5590", "vendor_name_as_billed": "Kestrel Industrial Supply",
            "po_number": "PO-4402", "invoice_date": "2026-03-05", "currency": "USD",
            "service_period": None,
            "lines": [line(1, "Nitrile Gloves", 480, "EACH", 2.00, 960.00)],
            "net_amount": 960.00, "tax_amount": 72.00, "gross_amount": 1032.00,
        },
        "expected": {
            "disposition": "APPROVE_FOR_PAYMENT", "payable_amount": 1032.00,
            "currency": "USD", "required_approver_role": "AP_CLERK",
            "must_cite": [], "defects": [],
            "rationale_key_facts": [
                "480 EACH divided by pack size 12 equals the 40 CASE ordered and received.",
                "$2.00 per EACH times 12 equals the $24.00 per CASE on the PO.",
            ],
        },
    },
    # ------------------------------------------------- 003 price variance within tolerance
    {
        "id": "CASE-003",
        "title": "Price variance inside tolerance",
        "tests": "Tolerance arithmetic: min(2%, $50).",
        "vendor": vendor("meridian"),
        "po": {
            "po_number": "PO-4403", "type": "GOODS", "currency": "USD",
            "buyer": "Dele Fashanu", "po_date": "2026-02-11",
            "lines": [line(1, "Toner Cartridge TN-450", 100, "EACH", 62.00, 6200.00)],
        },
        "receipt": {
            "receipt_number": "GR-7703", "po_number": "PO-4403",
            "received_date": "2026-03-01",
            "lines": [{"line": 1, "quantity": 100, "uom": "EACH"}],
        },
        "invoice": {
            "invoice_number": "INV-88144", "vendor_name_as_billed": "Meridian Paper Co",
            "po_number": "PO-4403", "invoice_date": "2026-03-03", "currency": "USD",
            "service_period": None,
            "lines": [line(1, "Toner Cartridge TN-450", 100, "EACH", 63.10, 6310.00)],
            "net_amount": 6310.00, "tax_amount": 473.25, "gross_amount": 6783.25,
        },
        "expected": {
            "disposition": "APPROVE_FOR_PAYMENT", "payable_amount": 6783.25,
            "currency": "USD", "required_approver_role": "AP_CLERK",
            "must_cite": [], "defects": [],
            "rationale_key_facts": [
                "Variance of $1.10 per unit is 1.77%, inside the 2% band.",
                "Tolerance is min(2% of $62.00 = $1.24, $50.00) = $1.24; $1.10 is within it.",
            ],
        },
    },
    # --------------------------------------------- 004 price variance outside, unauthorised
    {
        "id": "CASE-004",
        "title": "Price variance outside tolerance, supplier-asserted only",
        "tests": "A supplier notice is not an authorisation.",
        "vendor": vendor("kestrel"),
        "po": {
            "po_number": "PO-4404", "type": "GOODS", "currency": "USD",
            "buyer": "Dele Fashanu", "po_date": "2026-02-05",
            "lines": [line(1, "Safety Harness Model H7", 80, "EACH", 145.00, 11600.00)],
        },
        "receipt": {
            "receipt_number": "GR-7704", "po_number": "PO-4404",
            "received_date": "2026-02-28",
            "lines": [{"line": 1, "quantity": 80, "uom": "EACH"}],
        },
        "invoice": {
            "invoice_number": "INV-5612", "vendor_name_as_billed": "Kestrel Industrial Supply",
            "po_number": "PO-4404", "invoice_date": "2026-03-02", "currency": "USD",
            "service_period": None,
            "lines": [line(1, "Safety Harness Model H7", 80, "EACH", 154.00, 12320.00)],
            "net_amount": 12320.00, "tax_amount": 924.00, "gross_amount": 13244.00,
        },
        "correspondence": {
            "supplier_price_notice.txt": """From: billing@kestrel-industrial.example
To: ap@northgate-manufacturing.example
Date: Mon, 2 Mar 2026 09:14:00 +0000
Subject: Price adjustment notice - effective immediately

Hello,

Please note that due to sustained increases in raw steel and webbing costs, Kestrel
Industrial Supply has adjusted list pricing on all fall-protection product lines by 6.2%
with immediate effect. This adjustment is reflected on invoice INV-5612 against PO-4404.

We have applied the new pricing to open purchase orders as our standard terms permit
price adjustment on undelivered balances.

Regards,
Marta Oyelaran
Billing, Kestrel Industrial Supply
""",
        },
        "expected": {
            "disposition": "HOLD_PRICE_VARIANCE", "payable_amount": 0.00,
            "currency": "USD", "required_approver_role": "AP_CLERK",
            "must_cite": ["correspondence/supplier_price_notice.txt"],
            "defects": ["price_variance_uncured"],
            "rationale_key_facts": [
                "Variance of $9.00 per unit far exceeds the $2.90 tolerance.",
                "The only evidence is a supplier-issued notice; no authorised buyer approved it.",
                "Clause 3.1 requires buyer authorisation, which is absent.",
            ],
        },
    },
    # ------------------------------------------------- 005 price variance CURED by approval
    {
        "id": "CASE-005",
        "title": "Price variance outside tolerance, cured by buyer authorisation",
        "tests": "Judgment over rules: the email changes the answer.",
        "vendor": vendor("kestrel"),
        "po": {
            "po_number": "PO-4405", "type": "GOODS", "currency": "USD",
            "buyer": "Dele Fashanu", "po_date": "2026-02-09",
            "lines": [line(1, "Steel Conduit 20mm, 3m length", 60, "EACH", 88.00, 5280.00)],
        },
        "receipt": {
            "receipt_number": "GR-7705", "po_number": "PO-4405",
            "received_date": "2026-03-03",
            "lines": [{"line": 1, "quantity": 60, "uom": "EACH"}],
        },
        "invoice": {
            "invoice_number": "INV-5620", "vendor_name_as_billed": "Kestrel Industrial Supply",
            "po_number": "PO-4405", "invoice_date": "2026-03-04", "currency": "USD",
            "service_period": None,
            "lines": [line(1, "Steel Conduit 20mm, 3m length", 60, "EACH", 93.28, 5596.80)],
            "net_amount": 5596.80, "tax_amount": 419.76, "gross_amount": 6016.56,
        },
        "correspondence": {
            "surcharge_approval.txt": """From: sales@kestrel-industrial.example
To: dele.fashanu@northgate-manufacturing.example
Date: Thu, 26 Feb 2026 11:02:00 +0000
Subject: PO-4405 - request for surcharge approval

Dele,

The conduit mill has applied an alloy surcharge to our March allocation. To ship PO-4405
complete this week we would need to pass through a 6% surcharge on the conduit line only.
If that is not acceptable we can hold the order until April at the original price.

Please confirm either way.

Tunde Alabi
Kestrel Industrial Supply

--- reply ---

From: dele.fashanu@northgate-manufacturing.example
To: sales@kestrel-industrial.example
Date: Thu, 26 Feb 2026 15:47:00 +0000
Subject: RE: PO-4405 - request for surcharge approval

Tunde,

Approved - up to 6% on PO-4405, conduit line only. We need it on site this week so please
ship complete. This approval does not extend to any other open PO.

Dele Fashanu
Procurement, Northgate Manufacturing
""",
        },
        "expected": {
            "disposition": "APPROVE_FOR_PAYMENT", "payable_amount": 6016.56,
            "currency": "USD", "required_approver_role": "AP_CLERK",
            "must_cite": ["correspondence/surcharge_approval.txt"],
            "defects": [],
            "rationale_key_facts": [
                "Variance of $5.28 per unit is 6.0%, outside the $1.76 tolerance.",
                "Dele Fashanu is an authorised buyer and approved up to 6% on PO-4405 by name.",
                "Clause 3.1 is satisfied, so the variance is cured and paid as invoiced.",
            ],
        },
    },
    # ---------------------------------------------------------------- 006 partial delivery
    {
        "id": "CASE-006",
        "title": "Partial delivery billed in full",
        "tests": "Short-pay arithmetic on the received quantity.",
        "vendor": vendor("meridian"),
        "po": {
            "po_number": "PO-4406", "type": "GOODS", "currency": "USD",
            "buyer": "Priya Raman", "po_date": "2026-02-14",
            "lines": [line(1, "Archive Storage Box", 100, "EACH", 9.50, 950.00)],
        },
        "receipt": {
            "receipt_number": "GR-7706", "po_number": "PO-4406",
            "received_date": "2026-03-05",
            "note": "Balance of 40 on backorder, no ETA confirmed.",
            "lines": [{"line": 1, "quantity": 60, "uom": "EACH"}],
        },
        "invoice": {
            "invoice_number": "INV-88160", "vendor_name_as_billed": "Meridian Paper Co",
            "po_number": "PO-4406", "invoice_date": "2026-03-07", "currency": "USD",
            "service_period": None,
            "lines": [line(1, "Archive Storage Box", 100, "EACH", 9.50, 950.00)],
            "net_amount": 950.00, "tax_amount": 71.25, "gross_amount": 1021.25,
        },
        "expected": {
            "disposition": "SHORT_PAY", "payable_amount": 612.75,
            "currency": "USD", "required_approver_role": "AP_CLERK",
            "must_cite": ["receipt.json"],
            "defects": ["quantity_shortfall"],
            "rationale_key_facts": [
                "Only 60 of 100 were received; 40 remain on backorder.",
                "Payable net is 60 x $9.50 = $570.00.",
                "Tax recomputed on $570.00 at 7.5% is $42.75, giving $612.75.",
            ],
        },
    },
    # ------------------------------------------------------------------- 007 true duplicate
    {
        "id": "CASE-007",
        "title": "Duplicate invoice under a vendor-name variant",
        "tests": "Entity resolution across name spellings.",
        "vendor": vendor(
            "nordwind",
            prior_invoices=[
                {
                    "invoice_number": "NW-9912",
                    "vendor_name_as_billed": "Nordwind Supply Co.",
                    "po_number": "PO-4407",
                    "gross_amount": 3225.00,
                    "invoice_date": "2026-02-27",
                    "service_period": None,
                    "status": "PAID",
                }
            ],
        ),
        "po": {
            "po_number": "PO-4407", "type": "GOODS", "currency": "USD",
            "buyer": "Priya Raman", "po_date": "2026-02-10",
            "lines": [line(1, "Pallet Rack Beam, 2700mm", 25, "EACH", 120.00, 3000.00)],
        },
        "receipt": {
            "receipt_number": "GR-7707", "po_number": "PO-4407",
            "received_date": "2026-02-24",
            "lines": [{"line": 1, "quantity": 25, "uom": "EACH"}],
        },
        "invoice": {
            "invoice_number": "INV-77201",
            "vendor_name_as_billed": "Nordwind Supply Company LLC",
            "po_number": "PO-4407", "invoice_date": "2026-03-18", "currency": "USD",
            "service_period": None,
            "lines": [line(1, "Pallet Rack Beam, 2700mm", 25, "EACH", 120.00, 3000.00)],
            "net_amount": 3000.00, "tax_amount": 225.00, "gross_amount": 3225.00,
        },
        "expected": {
            "disposition": "DUPLICATE_REJECT", "payable_amount": 0.00,
            "currency": "USD", "required_approver_role": "AP_CLERK",
            "must_cite": ["vendor.json"],
            "defects": ["duplicate"],
            "rationale_key_facts": [
                "NW-9912 was already paid against PO-4407 for the identical $3,225.00.",
                "'Nordwind Supply Co.' and 'Nordwind Supply Company LLC' normalise to the same vendor.",
                "Invoice dates are 19 days apart, inside the 45-day window.",
                "Neither invoice carries a service period, so clause 8.1 does not apply.",
            ],
        },
    },
    # ------------------------------------------------------- 008 legitimate recurring (trap)
    {
        "id": "CASE-008",
        "title": "Recurring retainer that looks like a duplicate",
        "tests": "TRAP. Punishes naive amount-matching duplicate logic.",
        "vendor": vendor(
            "halcyon",
            prior_invoices=[
                {
                    "invoice_number": "INV-3221",
                    "vendor_name_as_billed": "Halcyon Facilities Management Ltd",
                    "po_number": "PO-4408",
                    "gross_amount": 5160.00,
                    "invoice_date": "2026-02-01",
                    "service_period": "2026-02-01/2026-02-28",
                    "status": "PAID",
                }
            ],
        ),
        "po": {
            "po_number": "PO-4408", "type": "SERVICES", "currency": "USD",
            "buyer": "Dele Fashanu", "po_date": "2026-01-02",
            "note": "Blanket PO, monthly cleaning retainer, Jan-Dec 2026.",
            "lines": [line(1, "Monthly cleaning retainer", 1, "MONTH", 4800.00, 4800.00)],
        },
        "receipt": None,
        "invoice": {
            "invoice_number": "INV-3310",
            "vendor_name_as_billed": "Halcyon Facilities Management Ltd",
            "po_number": "PO-4408", "invoice_date": "2026-03-01", "currency": "USD",
            "service_period": "2026-03-01/2026-03-31",
            "lines": [line(1, "Monthly cleaning retainer - March 2026", 1, "MONTH", 4800.00, 4800.00)],
            "net_amount": 4800.00, "tax_amount": 360.00, "gross_amount": 5160.00,
        },
        "expected": {
            "disposition": "APPROVE_FOR_PAYMENT", "payable_amount": 5160.00,
            "currency": "USD", "required_approver_role": "AP_CLERK",
            "must_cite": ["invoice.json"],
            "defects": [],
            "rationale_key_facts": [
                "Same vendor, PO and amount as INV-3221, which is why it looks like a duplicate.",
                "Service periods are distinct and non-overlapping: February versus March.",
                "Clause 8.1 makes this a legitimate recurring charge, not a duplicate.",
                "SERVICES PO, so no goods receipt is expected under clause 1.",
            ],
        },
    },
    # ------------------------------------------------------------ 009 freight within contract
    {
        "id": "CASE-009",
        "title": "Freight line absent from the PO",
        "tests": "Contract clause retrieval and the $500 ceiling.",
        "vendor": vendor("kestrel"),
        "po": {
            "po_number": "PO-4409", "type": "GOODS", "currency": "USD",
            "buyer": "Priya Raman", "po_date": "2026-02-22",
            "lines": [line(1, "Hex Bolt M12, box of 100", 150, "EACH", 18.00, 2700.00)],
        },
        "receipt": {
            "receipt_number": "GR-7709", "po_number": "PO-4409",
            "received_date": "2026-03-06",
            "note": "Expedited overnight freight requested by production.",
            "lines": [{"line": 1, "quantity": 150, "uom": "EACH"}],
        },
        "invoice": {
            "invoice_number": "INV-5641", "vendor_name_as_billed": "Kestrel Industrial Supply",
            "po_number": "PO-4409", "invoice_date": "2026-03-08", "currency": "USD",
            "service_period": None,
            "lines": [
                line(1, "Hex Bolt M12, box of 100", 150, "EACH", 18.00, 2700.00),
                line(2, "Expedited freight surcharge", 1, "EACH", 380.00, 380.00),
            ],
            "net_amount": 3080.00, "tax_amount": 231.00, "gross_amount": 3311.00,
        },
        "contract": """# Supply Agreement - Kestrel Industrial Supply

**Agreement:** NGM-KIS-2025-11
**Parties:** Northgate Manufacturing (Buyer) and Kestrel Industrial Supply (Supplier)
**Term:** 1 December 2025 - 30 November 2026

## Clause 6 - Delivery and freight

6.1 Standard ground freight on orders above $1,000 is included in unit pricing and shall
not be separately invoiced.

6.2 Where the Buyer requests expedited or overnight delivery, the Supplier may pass through
the actual carrier charge as a separate invoice line, **provided that such charge does not
exceed $500.00 per shipment**. Charges above that ceiling require prior written approval
from an authorised buyer.

6.3 Freight lines passed through under 6.2 are subject to sales tax on the same basis as
the goods supplied.

## Clause 9 - Price adjustment

9.1 Unit prices are firm for the term of this agreement. Any adjustment requires written
approval from an authorised buyer of the Buyer, referencing the affected purchase order.
""",
        "expected": {
            "disposition": "APPROVE_FOR_PAYMENT", "payable_amount": 3311.00,
            "currency": "USD", "required_approver_role": "AP_CLERK",
            "must_cite": ["contract.md"],
            "defects": [],
            "rationale_key_facts": [
                "Clause 6.2 permits pass-through of expedited freight up to $500.00.",
                "The $380.00 charge is inside that ceiling, so it is not an unauthorised surcharge.",
                "Receipt notes production requested expedited delivery.",
                "Clause 6.3 makes freight taxable, so tax is 7.5% of $3,080.00 = $231.00.",
            ],
        },
    },
    # ------------------------------------------------------------------ 010 wrong tax rate
    {
        "id": "CASE-010",
        "title": "Supplier applied the wrong tax rate",
        "tests": "Pure arithmetic trap. Independent tax recomputation.",
        "vendor": vendor("meridian"),
        "po": {
            "po_number": "PO-4410", "type": "GOODS", "currency": "USD",
            "buyer": "Dele Fashanu", "po_date": "2026-02-16",
            "lines": [line(1, "Laminating Pouch, pack of 100", 200, "EACH", 31.00, 6200.00)],
        },
        "receipt": {
            "receipt_number": "GR-7710", "po_number": "PO-4410",
            "received_date": "2026-03-09",
            "lines": [{"line": 1, "quantity": 200, "uom": "EACH"}],
        },
        "invoice": {
            "invoice_number": "INV-88192", "vendor_name_as_billed": "Meridian Paper Co",
            "po_number": "PO-4410", "invoice_date": "2026-03-11", "currency": "USD",
            "service_period": None,
            "lines": [line(1, "Laminating Pouch, pack of 100", 200, "EACH", 31.00, 6200.00)],
            "net_amount": 6200.00, "tax_amount": 744.00, "gross_amount": 6944.00,
        },
        "expected": {
            "disposition": "SHORT_PAY", "payable_amount": 6665.00,
            "currency": "USD", "required_approver_role": "AP_CLERK",
            "must_cite": ["vendor.json"],
            "defects": ["tax_discrepancy"],
            "rationale_key_facts": [
                "Goods and pricing match the PO and receipt exactly.",
                "Supplier billed $744.00 tax, which is 12% rather than the correct 7.5%.",
                "Correct tax on $6,200.00 is $465.00, giving a payable of $6,665.00.",
                "Overcharge of $279.00 is short-paid under clause 5.",
            ],
        },
    },
    # --------------------------------------------------------------- 011 currency mismatch
    {
        "id": "CASE-011",
        "title": "PO in EUR, invoice in USD",
        "tests": "Contract-fixed FX is normalisation, not a defect.",
        "vendor": vendor("rheinwerk"),
        "po": {
            "po_number": "PO-4411", "type": "GOODS", "currency": "EUR",
            "buyer": "Priya Raman", "po_date": "2026-01-28",
            "lines": [line(1, "Servo Drive SD-22", 40, "EACH", 210.00, 8400.00)],
        },
        "receipt": {
            "receipt_number": "GR-7711", "po_number": "PO-4411",
            "received_date": "2026-03-10",
            "lines": [{"line": 1, "quantity": 40, "uom": "EACH"}],
        },
        "invoice": {
            "invoice_number": "RW-2026-0451",
            "vendor_name_as_billed": "Rheinwerk Komponenten GmbH",
            "po_number": "PO-4411", "invoice_date": "2026-03-12", "currency": "USD",
            "service_period": None,
            "lines": [line(1, "Servo Drive SD-22", 40, "EACH", 231.00, 9240.00)],
            "net_amount": 9240.00, "tax_amount": 693.00, "gross_amount": 9933.00,
        },
        "contract": """# Supply Agreement - Rheinwerk Komponenten GmbH

**Agreement:** NGM-RKG-2026-01
**Term:** 1 January 2026 - 31 December 2026

## Clause 4 - Currency and exchange rate

4.1 Purchase orders are raised in EUR. The Supplier may invoice in USD at the Buyer's
request for treasury simplification.

4.2 For the period 1 January 2026 to 31 March 2026 the parties fix the conversion rate at
**EUR 1.00 = USD 1.10**. This rate shall be used for all invoices dated within the period,
irrespective of the prevailing market rate.

4.3 The fixed rate shall be renegotiated quarterly. Absent a agreed successor rate, PO
currency governs and USD invoicing is suspended.
""",
        "expected": {
            "disposition": "APPROVE_FOR_PAYMENT", "payable_amount": 9933.00,
            "currency": "USD", "required_approver_role": "AP_CLERK",
            "must_cite": ["contract.md"],
            "defects": [],
            "rationale_key_facts": [
                "Clause 4.2 fixes EUR 1.00 = USD 1.10 for invoices dated in Q1 2026.",
                "EUR 210.00 at the fixed rate is exactly USD 231.00, so there is no price variance.",
                "Payable is expressed in the invoice currency, USD, under clause 7.",
            ],
        },
    },
    # ------------------------------------------------------------------ 012 over-delivery
    {
        "id": "CASE-012",
        "title": "Over-delivery beyond the 5% band",
        "tests": "Over-receipt tolerance in the other direction.",
        "vendor": vendor("kestrel"),
        "po": {
            "po_number": "PO-4412", "type": "GOODS", "currency": "USD",
            "buyer": "Dele Fashanu", "po_date": "2026-02-19",
            "lines": [line(1, "Cable Gland M20", 100, "EACH", 7.40, 740.00)],
        },
        "receipt": {
            "receipt_number": "GR-7712", "po_number": "PO-4412",
            "received_date": "2026-03-11",
            "note": "Supplier shipped a full carton rather than the ordered count.",
            "lines": [{"line": 1, "quantity": 118, "uom": "EACH"}],
        },
        "invoice": {
            "invoice_number": "INV-5668", "vendor_name_as_billed": "Kestrel Industrial Supply",
            "po_number": "PO-4412", "invoice_date": "2026-03-13", "currency": "USD",
            "service_period": None,
            "lines": [line(1, "Cable Gland M20", 118, "EACH", 7.40, 873.20)],
            "net_amount": 873.20, "tax_amount": 65.49, "gross_amount": 938.69,
        },
        "expected": {
            "disposition": "HOLD_QUANTITY_VARIANCE", "payable_amount": 0.00,
            "currency": "USD", "required_approver_role": "AP_CLERK",
            "must_cite": ["receipt.json"],
            "defects": ["over_delivery"],
            "rationale_key_facts": [
                "118 received against 100 ordered is 18% over.",
                "Clause 4 tolerates 5%, which would cap acceptance at 105 units.",
                "Receiving must decide whether to keep or return the excess before payment.",
            ],
        },
    },
    # ------------------------------------------------------------- 013 services, no receipt
    {
        "id": "CASE-013",
        "title": "Services invoice with no goods receipt",
        "tests": "Two-way match. Absence of a receipt is not a defect here.",
        "vendor": vendor("ashgrove"),
        "po": {
            "po_number": "PO-4413", "type": "SERVICES", "currency": "USD",
            "buyer": "Dele Fashanu", "po_date": "2026-01-08",
            "lines": [line(1, "Contract review retainer, Q1 2026", 1, "EACH", 7500.00, 7500.00)],
        },
        "receipt": None,
        "invoice": {
            "invoice_number": "ALP-1188", "vendor_name_as_billed": "Ashgrove Legal Partners",
            "po_number": "PO-4413", "invoice_date": "2026-03-14", "currency": "USD",
            "service_period": "2026-01-01/2026-03-31",
            "lines": [line(1, "Contract review retainer, Q1 2026", 1, "EACH", 7500.00, 7500.00)],
            "net_amount": 7500.00, "tax_amount": 562.50, "gross_amount": 8062.50,
        },
        "expected": {
            "disposition": "APPROVE_FOR_PAYMENT", "payable_amount": 8062.50,
            "currency": "USD", "required_approver_role": "AP_CLERK",
            "must_cite": ["po.json"],
            "defects": [],
            "rationale_key_facts": [
                "PO type is SERVICES, so clause 1 requires a two-way match only.",
                "The missing goods receipt is expected and is not a defect.",
                "Invoice matches the PO exactly at $7,500.00 net.",
            ],
        },
    },
    # ------------------------------------------------------------------- 014 the hard case
    {
        "id": "CASE-014",
        "title": "Multi-defect: partial delivery, wrong tax rate, open credit memo, over threshold",
        "tests": "THE HARD ONE. Four interacting corrections then escalation.",
        "vendor": vendor(
            "kestrel",
            pack_sizes={"CASE": 25},
            open_credit_memos=[
                {
                    "credit_memo_number": "CM-2026-014",
                    "issued_date": "2026-02-20",
                    "amount": 1500.00,
                    "reason": "Short-ship on PO-4390, agreed settlement.",
                    "status": "OPEN",
                }
            ],
        ),
        "po": {
            "po_number": "PO-4414", "type": "GOODS", "currency": "USD",
            "buyer": "Priya Raman", "po_date": "2026-01-30",
            "lines": [line(1, "Industrial Wipe, 25 per case", 1200, "CASE", 30.00, 36000.00)],
        },
        "receipt": {
            "receipt_number": "GR-7714", "po_number": "PO-4414",
            "received_date": "2026-03-15",
            "note": "150 cases short. Supplier confirmed balance ships in April.",
            "lines": [{"line": 1, "quantity": 1050, "uom": "CASE"}],
        },
        "invoice": {
            "invoice_number": "INV-5702", "vendor_name_as_billed": "Kestrel Industrial Supply",
            "po_number": "PO-4414", "invoice_date": "2026-03-17", "currency": "USD",
            "service_period": None,
            "lines": [line(1, "Industrial Wipe", 30000, "EACH", 1.20, 36000.00)],
            "net_amount": 36000.00, "tax_amount": 3240.00, "gross_amount": 39240.00,
        },
        "expected": {
            "disposition": "ESCALATE_HUMAN", "payable_amount": 32362.50,
            "currency": "USD", "required_approver_role": "CONTROLLER",
            "must_cite": ["receipt.json", "vendor.json"],
            "defects": ["quantity_shortfall", "tax_discrepancy"],
            "rationale_key_facts": [
                "Invoice bills 30,000 EACH; at pack size 25 that is the full 1,200 CASE ordered.",
                "Only 1,050 CASE (26,250 EACH) were received, so 150 CASE were never delivered.",
                "Payable net is 26,250 x $1.20 = $31,500.00.",
                "Supplier billed tax at 9%; the correct rate is 7.5%, giving $2,362.50.",
                "Open credit memo CM-2026-014 for $1,500.00 nets down to $32,362.50.",
                "Two defects and a payable above $25,000 both trigger clause 11 escalation.",
                "Above $25,000 the approver is the CONTROLLER under clause 10.",
            ],
        },
    },

    # =========================================================================
    # Cases 015-024 -- policy BRANCH COVERAGE.
    #
    # The first fourteen cases each test a scenario. Measuring them exposed the
    # problem with that: a single prompt carrying the policy resolved all
    # fourteen, so nothing built on top of it could show a gain. The cases were
    # not wrong, they were incomplete -- they exercised one side of each policy
    # rule and left the other side untested.
    #
    # These ten close the gaps, each pinned to a specific clause branch:
    #   015  several lines, each needing different treatment, then aggregation
    #   016  the $50.00 cap binding *below* the 2% band (clause 3 "whichever is LOWER")
    #   017  authorisation that exists but fails clause 3.1, plus a wrong-PO distractor
    #   018  freight permitted by contract but over the clause 6 cap
    #   019  tax UNDER-charge -- pay more than billed (clause 5, third bullet)
    #   020  over-delivery WITHIN the 5% band -- not a defect (clause 4)
    #   021  credit memo larger than the invoice -- floor at $0.00 (clause 9)
    #   022  same amount, same PO, but OVERLAPPING service periods (clause 8.1 fails)
    #   023  variance cured by a covering ceiling rather than a specific figure (clause 3.1.3)
    #   024  the AP_MANAGER approval band, which no earlier case reached (clause 10)
    # =========================================================================

    # ------------------------------------------------- 015 multi-line aggregation
    {
        "id": "CASE-015",
        "title": "Four lines, four different treatments, then aggregation",
        "tests": "Breadth. Each line is individually easy; the invoice is only right "
                 "if all four are handled and summed correctly.",
        "vendor": vendor("kestrel"),
        "po": {
            "po_number": "PO-4415", "type": "GOODS", "currency": "USD",
            "buyer": "Priya Raman", "po_date": "2026-02-11",
            "lines": [
                line(1, "Junction Box 100mm", 150, "EACH", 6.40, 960.00),
                line(2, "Steel Conduit 20mm, 3m length", 480, "EACH", 2.05, 984.00),
                line(3, "Mounting Bracket, galvanised", 40, "EACH", 45.00, 1800.00),
                line(4, "Gland Plate, 6-way", 25, "EACH", 120.00, 3000.00),
            ],
        },
        "receipt": {
            "receipt_number": "GR-7715", "po_number": "PO-4415",
            "received_date": "2026-03-09",
            "note": "Gland plates part-shipped; balance on back order.",
            "lines": [
                {"line": 1, "quantity": 150, "uom": "EACH"},
                {"line": 2, "quantity": 480, "uom": "EACH"},
                {"line": 3, "quantity": 40, "uom": "EACH"},
                {"line": 4, "quantity": 20, "uom": "EACH"},
            ],
        },
        "invoice": {
            "invoice_number": "INV-5710", "vendor_name_as_billed": "Kestrel Industrial Supply",
            "po_number": "PO-4415", "invoice_date": "2026-03-12", "currency": "USD",
            "service_period": None,
            "lines": [
                line(1, "Junction Box 100mm", 150, "EACH", 6.40, 960.00),
                line(2, "Steel Conduit 20mm, 3m length", 40, "CASE", 24.60, 984.00),
                line(3, "Mounting Bracket, galvanised", 40, "EACH", 45.80, 1832.00),
                line(4, "Gland Plate, 6-way", 25, "EACH", 120.00, 3000.00),
            ],
            "net_amount": 6776.00, "tax_amount": 609.84, "gross_amount": 7385.84,
        },
        "expected": {
            "disposition": "ESCALATE_HUMAN", "payable_amount": 6639.20,
            "currency": "USD", "required_approver_role": "AP_CLERK",
            "must_cite": ["receipt.json", "vendor.json"],
            "defects": ["quantity_shortfall", "tax_discrepancy"],
            "rationale_key_facts": [
                "Line 1 matches exactly: $960.00.",
                "Line 2 is billed in CASE; at pack size 12 that is 480 EACH at $2.05, "
                "identical to the PO. Normalisation, not a defect: $984.00.",
                "Line 3 is $45.80 against a PO price of $45.00. Tolerance is the lower of "
                "2% ($0.90) and $50.00, so $0.90; the $0.80 increase is inside it. "
                "Pay the invoiced price: $1,832.00.",
                "Line 4 billed 25 but only 20 were received, so pay 20 x $120.00 = $2,400.00.",
                "Corrected net is $6,176.00.",
                "Supplier billed tax at 9%; at the vendor's 7.5% the correct tax is $463.20.",
                "Corrected gross is $6,639.20.",
                "Two defects trigger clause 11 escalation even though the amount is small.",
            ],
        },
    },
    # ------------------------------------------- 016 the $50 cap binds below the 2%
    {
        "id": "CASE-016",
        "title": "Price variance inside 2% but outside the $50.00 per-line cap",
        "tests": "Clause 3 says the tolerance is the LOWER of 2% and $50.00. On a "
                 "high-priced line the cap binds first. Reading only the percentage "
                 "approves an unauthorised increase.",
        "vendor": vendor("meridian"),
        "po": {
            "po_number": "PO-4416", "type": "GOODS", "currency": "USD",
            "buyer": "Dele Fashanu", "po_date": "2026-02-16",
            "lines": [line(1, "Offset Print Cylinder, 720mm", 2, "EACH", 4000.00, 8000.00)],
        },
        "receipt": {
            "receipt_number": "GR-7716", "po_number": "PO-4416",
            "received_date": "2026-03-10",
            "lines": [{"line": 1, "quantity": 2, "uom": "EACH"}],
        },
        "invoice": {
            "invoice_number": "INV-88220", "vendor_name_as_billed": "Meridian Paper Co",
            "po_number": "PO-4416", "invoice_date": "2026-03-11", "currency": "USD",
            "service_period": None,
            "lines": [line(1, "Offset Print Cylinder, 720mm", 2, "EACH", 4075.00, 8150.00)],
            "net_amount": 8150.00, "tax_amount": 611.25, "gross_amount": 8761.25,
        },
        "expected": {
            "disposition": "HOLD_PRICE_VARIANCE", "payable_amount": 0.00,
            "currency": "USD", "required_approver_role": "AP_CLERK",
            "must_cite": ["po.json"],
            "defects": ["price_variance_uncured"],
            "rationale_key_facts": [
                "The increase is $75.00 per unit on a PO price of $4,000.00.",
                "As a percentage that is 1.875%, which is inside the 2% band.",
                "But 2% of $4,000.00 is $80.00, and the tolerance is the LOWER of that "
                "and $50.00, so the tolerance is $50.00.",
                "$75.00 exceeds $50.00, so the variance is outside tolerance.",
                "No authorisation is present, so clause 3.1 does not cure it.",
            ],
        },
    },
    # ------------------------------- 017 authorisation present but fails clause 3.1
    {
        "id": "CASE-017",
        "title": "Price increase approved by someone with no authority, plus a wrong-PO decoy",
        "tests": "Clause 3.1 needs all three conditions. Here an approval exists and "
                 "reads convincingly, but the approver is not an authorised buyer -- "
                 "and a genuine authorised buyer's approval is present for a different PO.",
        "vendor": vendor("kestrel"),
        "po": {
            "po_number": "PO-4417", "type": "GOODS", "currency": "USD",
            "buyer": "Priya Raman", "po_date": "2026-02-06",
            "lines": [line(1, "Armoured Cable 4c 16mm", 500, "EACH", 18.00, 9000.00)],
        },
        "receipt": {
            "receipt_number": "GR-7717", "po_number": "PO-4417",
            "received_date": "2026-03-13",
            "lines": [{"line": 1, "quantity": 500, "uom": "EACH"}],
        },
        "invoice": {
            "invoice_number": "INV-5711", "vendor_name_as_billed": "Kestrel Industrial Supply",
            "po_number": "PO-4417", "invoice_date": "2026-03-16", "currency": "USD",
            "service_period": None,
            "lines": [line(1, "Armoured Cable 4c 16mm", 500, "EACH", 19.60, 9800.00)],
            "net_amount": 9800.00, "tax_amount": 735.00, "gross_amount": 10535.00,
        },
        "correspondence": {
            "price_increase_approval.txt": """From: sales@kestrel-industrial.example
To: femi.okonkwo@northgate-manufacturing.example
Date: Mon, 09 Mar 2026 08:31:00 +0000
Subject: PO-4417 - copper surcharge

Femi,

Copper has moved again and we need to apply $1.60/m to the armoured cable on PO-4417,
taking it to $19.60. We can ship Thursday if you are happy with that.

Tunde Alabi
Kestrel Industrial Supply

--- reply ---

From: femi.okonkwo@northgate-manufacturing.example
To: sales@kestrel-industrial.example
Date: Mon, 09 Mar 2026 09:05:00 +0000
Subject: RE: PO-4417 - copper surcharge

Tunde,

That's fine, go ahead and ship Thursday at $19.60. We need the cable on site.

Femi Okonkwo
Warehouse Supervisor, Northgate Manufacturing
""",
            "unrelated_approval.txt": """From: dele.fashanu@northgate-manufacturing.example
To: sales@kestrel-industrial.example
Date: Thu, 26 Feb 2026 15:47:00 +0000
Subject: RE: PO-4405 - request for surcharge approval

Tunde,

Approved - up to 6% on PO-4405, conduit line only. We need it on site this week so please
ship complete. This approval does not extend to any other open PO.

Dele Fashanu
Procurement, Northgate Manufacturing
""",
        },
        "expected": {
            "disposition": "HOLD_PRICE_VARIANCE", "payable_amount": 0.00,
            "currency": "USD", "required_approver_role": "AP_CLERK",
            "must_cite": ["correspondence/price_increase_approval.txt"],
            "defects": ["price_variance_uncured"],
            "rationale_key_facts": [
                "The increase is $1.60 on a PO price of $18.00; tolerance is the lower of "
                "2% ($0.36) and $50.00, so $0.36. The variance is outside tolerance.",
                "Femi Okonkwo approved it, but vendor.json lists only Dele Fashanu and "
                "Priya Raman as authorised buyers, so clause 3.1 condition 1 fails.",
                "The other approval on file is from Dele Fashanu but references PO-4405, "
                "not PO-4417, so it fails clause 3.1 condition 2.",
                "The variance is uncured.",
            ],
        },
    },
    # ------------------------------------------ 018 freight permitted but over the cap
    {
        "id": "CASE-018",
        "title": "Freight expressly permitted by contract but above the $500.00 limit",
        "tests": "Clause 6 needs both conditions. The contract permits the charge, "
                 "which is the half an agent is likely to find and stop at.",
        "vendor": vendor("kestrel"),
        "po": {
            "po_number": "PO-4418", "type": "GOODS", "currency": "USD",
            "buyer": "Dele Fashanu", "po_date": "2026-02-23",
            "lines": [line(1, "Cable Drum 500m, SWA 4c", 6, "EACH", 410.00, 2460.00)],
        },
        "receipt": {
            "receipt_number": "GR-7718", "po_number": "PO-4418",
            "received_date": "2026-03-17",
            "lines": [{"line": 1, "quantity": 6, "uom": "EACH"}],
        },
        "invoice": {
            "invoice_number": "INV-5712", "vendor_name_as_billed": "Kestrel Industrial Supply",
            "po_number": "PO-4418", "invoice_date": "2026-03-19", "currency": "USD",
            "service_period": None,
            "lines": [
                line(1, "Cable Drum 500m, SWA 4c", 6, "EACH", 410.00, 2460.00),
                line(2, "Delivery and handling, oversize drums", 1, "EACH", 640.00, 640.00),
            ],
            "net_amount": 3100.00, "tax_amount": 232.50, "gross_amount": 3332.50,
        },
        "contract": """# Supply Agreement - Kestrel Industrial Supply

**Agreement:** KIS-2026-02
**Parties:** Northgate Manufacturing and Kestrel Industrial Supply
**Term:** 1 January 2026 - 31 December 2026

## 3. Pricing

3.1 Prices are as stated on each purchase order.

## 6. Delivery

6.1 Standard ground delivery is included in the quoted line prices.

6.2 Where an order requires oversize or dedicated transport, Kestrel may pass through the
    documented carrier cost as a separate delivery and handling line on the invoice.

6.3 Nothing in clause 6.2 overrides Northgate's internal approval limits for non-PO charges.
""",
        "expected": {
            "disposition": "HOLD_PRICE_VARIANCE", "payable_amount": 0.00,
            "currency": "USD", "required_approver_role": "AP_CLERK",
            "must_cite": ["contract.md"],
            "defects": ["unauthorised_surcharge"],
            "rationale_key_facts": [
                "Contract clause 6.2 does permit a delivery and handling pass-through, so "
                "the first condition of policy clause 6 is met.",
                "The charge is $640.00, which exceeds the $500.00 limit, so the second "
                "condition fails.",
                "Clause 6 requires both, so the line is an unauthorised surcharge.",
            ],
        },
    },
    # --------------------------------------------------- 019 tax under-charged
    {
        "id": "CASE-019",
        "title": "Supplier under-charged tax; the correct payable is higher than billed",
        "tests": "Clause 5's counterintuitive branch. Every other tax case reduces the "
                 "payable, so an agent that has learned 'tax defect means pay less' "
                 "gets both the amount and the direction wrong.",
        "vendor": vendor("meridian"),
        "po": {
            "po_number": "PO-4419", "type": "GOODS", "currency": "USD",
            "buyer": "Dele Fashanu", "po_date": "2026-02-27",
            "lines": [line(1, "Carton Sealing Tape 48mm", 400, "EACH", 3.25, 1300.00)],
        },
        "receipt": {
            "receipt_number": "GR-7719", "po_number": "PO-4419",
            "received_date": "2026-03-18",
            "lines": [{"line": 1, "quantity": 400, "uom": "EACH"}],
        },
        "invoice": {
            "invoice_number": "INV-88221", "vendor_name_as_billed": "Meridian Paper Co",
            "po_number": "PO-4419", "invoice_date": "2026-03-20", "currency": "USD",
            "service_period": None,
            "lines": [line(1, "Carton Sealing Tape 48mm", 400, "EACH", 3.25, 1300.00)],
            "net_amount": 1300.00, "tax_amount": 65.00, "gross_amount": 1365.00,
        },
        "expected": {
            "disposition": "APPROVE_FOR_PAYMENT", "payable_amount": 1397.50,
            "currency": "USD", "required_approver_role": "AP_CLERK",
            "must_cite": ["vendor.json"],
            "defects": ["tax_discrepancy"],
            "rationale_key_facts": [
                "Quantity and price match the PO and the receipt exactly.",
                "The supplier billed $65.00 of tax, which is 5% of the net.",
                "The vendor's rate is 7.5%, so the correct tax on $1,300.00 is $97.50.",
                "Clause 5 says an under-charge is paid at the recomputed higher total: "
                "$1,397.50, which is more than the supplier asked for.",
                "It is still a defect and must be flagged as a tax-compliance exposure.",
            ],
        },
    },
    # ------------------------------------------ 020 over-delivery inside the 5% band
    {
        "id": "CASE-020",
        "title": "Over-delivery of 3% -- inside the tolerated band",
        "tests": "The other side of clause 4 from CASE-012. An agent that holds any "
                 "over-delivery blocks a legitimate invoice.",
        "vendor": vendor("kestrel"),
        "po": {
            "po_number": "PO-4420", "type": "GOODS", "currency": "USD",
            "buyer": "Dele Fashanu", "po_date": "2026-03-02",
            "lines": [line(1, "Cable Gland M25", 200, "EACH", 8.10, 1620.00)],
        },
        "receipt": {
            "receipt_number": "GR-7720", "po_number": "PO-4420",
            "received_date": "2026-03-19",
            "note": "Supplier shipped a full carton rather than the ordered count.",
            "lines": [{"line": 1, "quantity": 206, "uom": "EACH"}],
        },
        "invoice": {
            "invoice_number": "INV-5713", "vendor_name_as_billed": "Kestrel Industrial Supply",
            "po_number": "PO-4420", "invoice_date": "2026-03-21", "currency": "USD",
            "service_period": None,
            "lines": [line(1, "Cable Gland M25", 206, "EACH", 8.10, 1668.60)],
            "net_amount": 1668.60, "tax_amount": 125.15, "gross_amount": 1793.75,
        },
        "expected": {
            "disposition": "APPROVE_FOR_PAYMENT", "payable_amount": 1793.75,
            "currency": "USD", "required_approver_role": "AP_CLERK",
            "must_cite": ["receipt.json"],
            "defects": [],
            "rationale_key_facts": [
                "206 received against 200 ordered is 3% over, inside the 5% band.",
                "Clause 4 says pay for the received quantity and treat it as clean.",
                "Recomputed tax at 7.5% of $1,668.60 is $125.145, and the supplier billed "
                "$125.15 -- inside the $0.02 rounding allowance, so not a defect.",
                "This invoice has no defects at all.",
            ],
        },
    },
    # ------------------------------------------- 021 credit memo exceeds the invoice
    {
        "id": "CASE-021",
        "title": "Open credit memo larger than the invoice -- payable floors at zero",
        "tests": "Clause 9's floor. A payable of $0.00 that is nonetheless an APPROVE, "
                 "not a hold -- the amount and the disposition pull in opposite directions.",
        "vendor": vendor(
            "meridian",
            open_credit_memos=[
                {
                    "credit_memo_number": "CM-2026-021",
                    "issued_date": "2026-03-02",
                    "amount": 2000.00,
                    "reason": "Overbilling on PO-4372, agreed settlement.",
                    "status": "OPEN",
                }
            ],
        ),
        "po": {
            "po_number": "PO-4421", "type": "GOODS", "currency": "USD",
            "buyer": "Priya Raman", "po_date": "2026-03-03",
            "lines": [line(1, "Copier Toner Cartridge, black", 12, "EACH", 118.00, 1416.00)],
        },
        "receipt": {
            "receipt_number": "GR-7721", "po_number": "PO-4421",
            "received_date": "2026-03-20",
            "lines": [{"line": 1, "quantity": 12, "uom": "EACH"}],
        },
        "invoice": {
            "invoice_number": "INV-88222", "vendor_name_as_billed": "Meridian Paper Co",
            "po_number": "PO-4421", "invoice_date": "2026-03-22", "currency": "USD",
            "service_period": None,
            "lines": [line(1, "Copier Toner Cartridge, black", 12, "EACH", 118.00, 1416.00)],
            "net_amount": 1416.00, "tax_amount": 106.20, "gross_amount": 1522.20,
        },
        "expected": {
            "disposition": "APPROVE_FOR_PAYMENT", "payable_amount": 0.00,
            "currency": "USD", "required_approver_role": "AP_CLERK",
            "must_cite": ["vendor.json"],
            "defects": [],
            "rationale_key_facts": [
                "The invoice itself is a clean three-way match at $1,522.20.",
                "Open credit memo CM-2026-021 is for $2,000.00, more than the invoice.",
                "Clause 9 nets it and floors the result at $0.00; a negative payable is "
                "never produced.",
                "Netting is explicitly not a defect, so this is an APPROVE at $0.00 "
                "rather than a hold. The $477.80 of unused credit stays open.",
            ],
        },
    },
    # ------------------------------- 022 overlapping service periods -> still a duplicate
    {
        "id": "CASE-022",
        "title": "Same PO and amount as a paid invoice, with OVERLAPPING service periods",
        "tests": "The mirror of CASE-008. There a distinct service period made a "
                 "near-duplicate legitimate; here the periods overlap, so clause 8.1 "
                 "does not rescue it. An agent that learned 'service period present "
                 "means recurring' pays twice.",
        "vendor": vendor(
            "halcyon",
            prior_invoices=[
                {
                    "invoice_number": "HL-3301",
                    "vendor_name_as_billed": "Halcyon Facilities Mgmt Limited",
                    "po_number": "PO-4422",
                    "gross_amount": 4300.00,
                    "invoice_date": "2026-02-14",
                    "service_period": "2026-02-01/2026-02-28",
                    "status": "PAID",
                }
            ],
        ),
        "po": {
            "po_number": "PO-4422", "type": "SERVICES", "currency": "USD",
            "buyer": "Dele Fashanu", "po_date": "2026-01-20",
            "lines": [line(1, "Grounds maintenance, monthly", 1, "MONTH", 4000.00, 4000.00)],
        },
        "receipt": None,
        "invoice": {
            "invoice_number": "INV-HL-3319",
            "vendor_name_as_billed": "Halcyon Facilities Management Ltd",
            "po_number": "PO-4422", "invoice_date": "2026-03-05", "currency": "USD",
            "service_period": "2026-02-15/2026-03-14",
            "lines": [line(1, "Grounds maintenance, monthly", 1, "MONTH", 4000.00, 4000.00)],
            "net_amount": 4000.00, "tax_amount": 300.00, "gross_amount": 4300.00,
        },
        "expected": {
            "disposition": "DUPLICATE_REJECT", "payable_amount": 0.00,
            "currency": "USD", "required_approver_role": "AP_CLERK",
            "must_cite": ["vendor.json"],
            "defects": ["suspected_duplicate"],
            "rationale_key_facts": [
                "Vendor matches HL-3301 after suffix normalisation (Ltd and Limited).",
                "Same PO-4422, gross identical at $4,300.00, and the dates are 19 days "
                "apart, inside the 45-day window.",
                "The service periods are 1-28 February and 15 February to 14 March. They "
                "overlap across 15-28 February.",
                "Clause 8.1 rescues only distinct, NON-overlapping periods, so it does not "
                "apply and every condition of clause 8 is met.",
                "SERVICES PO, so the absent goods receipt is normal and not a defect.",
            ],
        },
    },
    # --------------------------------------- 023 variance cured by a covering ceiling
    {
        "id": "CASE-023",
        "title": "Variance cured by a standing ceiling rather than a specific figure",
        "tests": "Clause 3.1 condition 3 accepts 'a ceiling that covers it'. The "
                 "authorisation never names $242.00, so a literal match fails and the "
                 "agent must reason about coverage.",
        "vendor": vendor("kestrel"),
        "po": {
            "po_number": "PO-4423", "type": "GOODS", "currency": "USD",
            "buyer": "Priya Raman", "po_date": "2026-02-13",
            "lines": [line(1, "Control Panel Enclosure IP66", 15, "EACH", 220.00, 3300.00)],
        },
        "receipt": {
            "receipt_number": "GR-7723", "po_number": "PO-4423",
            "received_date": "2026-03-16",
            "lines": [{"line": 1, "quantity": 15, "uom": "EACH"}],
        },
        "invoice": {
            "invoice_number": "INV-5714", "vendor_name_as_billed": "Kestrel Industrial Supply",
            "po_number": "PO-4423", "invoice_date": "2026-03-18", "currency": "USD",
            "service_period": None,
            "lines": [line(1, "Control Panel Enclosure IP66", 15, "EACH", 242.00, 3630.00)],
            "net_amount": 3630.00, "tax_amount": 272.25, "gross_amount": 3902.25,
        },
        "correspondence": {
            "ceiling_authorisation.txt": """From: priya.raman@northgate-manufacturing.example
To: sales@kestrel-industrial.example
Date: Fri, 27 Feb 2026 10:12:00 +0000
Subject: PO-4423 - enclosure pricing for the rest of Q1

Tunde,

Understood on the steel cost. Rather than go back and forth on each shipment: for PO-4423
you are authorised up to $250.00 per enclosure for the remainder of Q1. Invoice at your
actual cost within that ceiling and we will not query it.

Anything above $250.00 comes back to me first.

Priya Raman
Procurement, Northgate Manufacturing
""",
        },
        "expected": {
            "disposition": "APPROVE_FOR_PAYMENT", "payable_amount": 3902.25,
            "currency": "USD", "required_approver_role": "AP_CLERK",
            "must_cite": ["correspondence/ceiling_authorisation.txt"],
            "defects": [],
            "rationale_key_facts": [
                "The increase is $22.00 on a PO price of $220.00; tolerance is the lower "
                "of 2% ($4.40) and $50.00, so the variance is outside tolerance.",
                "Priya Raman is an authorised buyer, the note names PO-4423, and it sets a "
                "$250.00 ceiling that covers the invoiced $242.00.",
                "All three conditions of clause 3.1 are satisfied, so the variance is "
                "cured and is not a defect.",
                "A cured variance is paid at the invoiced price: $3,902.25.",
            ],
        },
    },
    # ------------------------------------------------ 024 the AP_MANAGER band
    {
        "id": "CASE-024",
        "title": "Short delivery landing the payable in the AP_MANAGER band",
        "tests": "No case among the first fourteen produced a payable between "
                 "$10,000.01 and $25,000.00, so the middle approval tier was never "
                 "exercised at all.",
        "vendor": vendor("meridian"),
        "po": {
            "po_number": "PO-4424", "type": "GOODS", "currency": "USD",
            "buyer": "Dele Fashanu", "po_date": "2026-02-02",
            "lines": [line(1, "Digital Press Consumable Kit", 60, "EACH", 320.00, 19200.00)],
        },
        "receipt": {
            "receipt_number": "GR-7724", "po_number": "PO-4424",
            "received_date": "2026-03-16",
            "note": "8 kits damaged in transit and refused at the dock.",
            "lines": [{"line": 1, "quantity": 52, "uom": "EACH"}],
        },
        "invoice": {
            "invoice_number": "INV-88223", "vendor_name_as_billed": "Meridian Paper Co",
            "po_number": "PO-4424", "invoice_date": "2026-03-19", "currency": "USD",
            "service_period": None,
            "lines": [line(1, "Digital Press Consumable Kit", 60, "EACH", 320.00, 19200.00)],
            "net_amount": 19200.00, "tax_amount": 1440.00, "gross_amount": 20640.00,
        },
        "expected": {
            "disposition": "SHORT_PAY", "payable_amount": 17888.00,
            "currency": "USD", "required_approver_role": "AP_MANAGER",
            "must_cite": ["receipt.json"],
            "defects": ["quantity_shortfall"],
            "rationale_key_facts": [
                "The invoice bills all 60 kits but only 52 were received and accepted.",
                "Corrected net is 52 x $320.00 = $16,640.00.",
                "Tax recomputed at 7.5% is $1,248.00, giving $17,888.00.",
                "One defect only, so clause 11 does not force escalation.",
                "$17,888.00 falls in the $10,000.01-$25,000.00 band, so the approver is "
                "the AP_MANAGER, not the clerk.",
            ],
        },
    },
]


# --------------------------------------------------------------------------------------
# Consistency checks -- catch typos without re-deriving the ground truth
# --------------------------------------------------------------------------------------

def check_consistency(case: dict) -> list[str]:
    """Validate the *documents*, not the answer."""
    problems: list[str] = []
    cid = case["id"]
    inv = case["invoice"]

    line_sum = round(sum(l["amount"] for l in inv["lines"]), 2)
    if line_sum != round(inv["net_amount"], 2):
        problems.append(f"{cid}: invoice lines sum to {line_sum}, net_amount is {inv['net_amount']}")

    gross = round(inv["net_amount"] + inv["tax_amount"], 2)
    if gross != round(inv["gross_amount"], 2):
        problems.append(f"{cid}: net + tax = {gross}, gross_amount is {inv['gross_amount']}")

    for l in inv["lines"]:
        amt = round(l["quantity"] * l["unit_price"], 2)
        if amt != round(l["amount"], 2):
            problems.append(
                f"{cid}: invoice line {l['line']} qty x price = {amt}, amount is {l['amount']}"
            )

    for l in case["po"]["lines"]:
        amt = round(l["quantity"] * l["unit_price"], 2)
        if amt != round(l["amount"], 2):
            problems.append(
                f"{cid}: PO line {l['line']} qty x price = {amt}, amount is {l['amount']}"
            )

    exp = case["expected"]
    valid = {
        "APPROVE_FOR_PAYMENT", "SHORT_PAY", "HOLD_PRICE_VARIANCE",
        "HOLD_QUANTITY_VARIANCE", "DUPLICATE_REJECT", "ESCALATE_HUMAN",
    }
    if exp["disposition"] not in valid:
        problems.append(f"{cid}: unknown disposition {exp['disposition']}")

    if exp["disposition"] in {"HOLD_PRICE_VARIANCE", "HOLD_QUANTITY_VARIANCE", "DUPLICATE_REJECT"}:
        if exp["payable_amount"] != 0.00:
            problems.append(f"{cid}: {exp['disposition']} must have payable 0.00")

    # Approval threshold must agree with the stated payable (policy clause 10).
    amt = exp["payable_amount"]
    expected_role = (
        "AP_CLERK" if amt <= 10000.00 else
        "AP_MANAGER" if amt <= 25000.00 else
        "CONTROLLER"
    )
    if exp["required_approver_role"] != expected_role:
        problems.append(
            f"{cid}: payable {amt} implies {expected_role}, "
            f"ground truth says {exp['required_approver_role']}"
        )

    # Clause 11: two or more defects, or payable above 25k, must escalate.
    if (len(exp["defects"]) >= 2 or amt > 25000.00) and exp["disposition"] != "ESCALATE_HUMAN":
        problems.append(f"{cid}: clause 11 should force ESCALATE_HUMAN")

    if case.get("receipt") is not None and case["receipt"]["po_number"] != case["po"]["po_number"]:
        problems.append(f"{cid}: receipt PO number does not match")
    if inv["po_number"] != case["po"]["po_number"]:
        problems.append(f"{cid}: invoice PO number does not match")

    return problems


def write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate the ClearQueue case dataset.")
    ap.add_argument("--out", default="cases", help="output directory (default: cases)")
    args = ap.parse_args()

    problems: list[str] = []
    for case in CASES:
        problems.extend(check_consistency(case))

    if problems:
        print("DATASET CONSISTENCY FAILURES:")
        for p in problems:
            print("  -", p)
        return 1

    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)

    manifest = []
    for case in CASES:
        d = out / case["id"]
        write_json(d / "po.json", case["po"])
        write_json(d / "invoice.json", case["invoice"])
        write_json(d / "vendor.json", case["vendor"])
        if case.get("receipt") is not None:
            write_json(d / "receipt.json", case["receipt"])
        if case.get("contract"):
            (d / "contract.md").write_text(case["contract"], encoding="utf-8")
        for name, body in (case.get("correspondence") or {}).items():
            p = d / "correspondence" / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body, encoding="utf-8")

        expected = {"case_id": case["id"], "title": case["title"], **case["expected"]}
        write_json(d / "expected.json", expected)

        manifest.append({
            "case_id": case["id"],
            "title": case["title"],
            "tests": case["tests"],
            "disposition": case["expected"]["disposition"],
            "payable_amount": case["expected"]["payable_amount"],
            "has_receipt": case.get("receipt") is not None,
            "has_contract": bool(case.get("contract")),
            "correspondence_files": sorted((case.get("correspondence") or {}).keys()),
        })

    write_json(out / "manifest.json", manifest)

    print(f"Wrote {len(CASES)} cases to {out}/")
    print("Consistency checks passed.")
    dist: dict[str, int] = {}
    for m in manifest:
        dist[m["disposition"]] = dist.get(m["disposition"], 0) + 1
    print("\nDisposition distribution:")
    for k in sorted(dist):
        print(f"  {k:<24} {dist[k]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
