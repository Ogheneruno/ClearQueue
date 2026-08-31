# Accounts Payable — Invoice Matching & Exception Policy

**Document ID:** AP-POL-2026-03
**Effective:** 1 January 2026
**Owner:** Controller's Office
**Applies to:** all supplier invoices entering the AP exception queue

This policy is the single source of truth for resolving invoice exceptions. Where this
document and an ERP configuration disagree, this document governs.

---

## 1. Match requirements

| PO type | Required documents | Notes |
| --- | --- | --- |
| **Goods** (`po.type == "GOODS"`) | PO + Goods Receipt + Invoice (**3-way**) | No receipt means nothing was delivered. Do not pay. |
| **Services** (`po.type == "SERVICES"`) | PO + Invoice (**2-way**) | A goods receipt is **not** expected. Absence of a receipt is not a defect. |

A missing goods receipt on a **GOODS** PO is a defect. A missing goods receipt on a
**SERVICES** PO is normal and must not be raised as an exception.

## 2. Unit-of-measure normalisation

Suppliers frequently invoice in a different unit than the PO was raised in. Before any
quantity or price comparison, normalise both sides to the **PO's unit of measure** using
`vendor.json → pack_sizes` (e.g. `{"CASE": 12}` means one CASE contains 12 EACH).

UOM normalisation is a **routine conversion, not a defect.** An invoice that reconciles
exactly once converted is a clean match.

Unit price must be normalised alongside quantity: a price of $2.00/EACH is equivalent to
$24.00/CASE where the pack size is 12.

## 3. Price tolerance

The invoiced unit price may exceed the PO unit price by up to **2% of the PO unit price, or
$50.00 per line, whichever is the LOWER amount**.

- Within tolerance → not a defect. Pay the invoiced price.
- Outside tolerance → **price variance defect**, unless clause 3.1 applies.

### 3.1 Authorised price variance

A price variance outside tolerance is **cured** — and ceases to be a defect — when the case
evidence contains written authorisation that satisfies **all** of:

1. it is from, or explicitly countersigned by, a person listed in `vendor.json → authorised_buyers`;
2. it references the specific PO number; and
3. it authorises the specific increase, surcharge, or a ceiling that covers it.

A supplier asserting a price increase **without** buyer authorisation does not cure the
variance. A cured variance is paid at the invoiced price.

## 4. Quantity rules

Quantities are compared **after** UOM normalisation (clause 2).

- **Under-delivery** (received < invoiced): never pay for goods not received. Disposition
  `SHORT_PAY`, calculated on the **received** quantity. This is a defect.
- **Over-delivery** (received > PO quantity): tolerated up to **5%** of the PO quantity.
  Within 5% → pay for the received quantity, not a defect. Beyond 5% →
  `HOLD_QUANTITY_VARIANCE`, a defect.
- Invoiced quantity exceeding received quantity is always resolved in favour of the receipt.

## 5. Tax

Recompute tax independently using `vendor.json → tax_rate` applied to the **corrected net
amount** (after clauses 2–4). Do not trust the supplier's tax figure.

- Supplier tax within **$0.02** of the recomputed figure → rounding, not a defect.
- Supplier **overcharged** tax → tax discrepancy defect. `SHORT_PAY` the corrected total.
- Supplier **undercharged** tax → pay the recomputed (higher) correct total. This is a
  defect and must be flagged, because it creates a tax-compliance exposure.

## 6. Freight, surcharges and other non-PO lines

An invoice line with no corresponding PO line is permitted only when **both** hold:

1. a contract clause in `contract.md` expressly permits passing that charge through; **and**
2. the charge is **$500.00 or less**.

Otherwise it is an unauthorised-surcharge defect → `HOLD_PRICE_VARIANCE`.

## 7. Currency

Where the invoice currency differs from the PO currency:

- If `contract.md` fixes an exchange rate for the period, apply it. This is normalisation,
  **not** a defect.
- If no contract rate exists, do not guess or use a market rate → `ESCALATE_HUMAN`.

The payable is always expressed in the **invoice** currency.

## 8. Duplicate detection

Treat an invoice as a duplicate only when **all** of the following hold against a prior
invoice in `vendor.json → prior_invoices`:

1. same vendor after name normalisation (ignore case, punctuation, and the suffixes
   `LTD, LLC, INC, CO, COMPANY, CORP, GMBH, PLC, LIMITED`);
2. same PO number;
3. gross amount equal within **$0.01**; and
4. invoice dates within **45 days** of each other; and
5. **no distinguishing service period** — see below.

### 8.1 Recurring charges are not duplicates

Invoices that carry distinct, non-overlapping `service_period` values are **legitimate
recurring charges**, not duplicates, even when the vendor, PO and amount are identical. A
monthly retainer bills the same amount every month by design.

Rejecting a legitimate recurring invoice as a duplicate is a **supplier-relationship
failure** and is treated as seriously as an overpayment.

## 9. Credit memos

Outstanding credit memos in `vendor.json → open_credit_memos` must be netted against the
payable before the approval threshold in clause 10 is applied. Net to a floor of $0.00;
never produce a negative payable.

## 10. Approval authority

Applied to the **final net payable**:

| Net payable | Required approver |
| --- | --- |
| $0.00 – $10,000.00 | `AP_CLERK` |
| $10,000.01 – $25,000.00 | `AP_MANAGER` |
| above $25,000.00 | `CONTROLLER` |

## 11. Escalation

Route to `ESCALATE_HUMAN` when any of the following hold:

- **two or more defects** are present on the same invoice; or
- the final net payable exceeds **$25,000.00**; or
- the evidence is contradictory or insufficient to decide (e.g. clause 7 with no contract rate).

Escalation still requires a **computed recommended payable** — the reviewer is being asked to
confirm a number, not to start from scratch.

### 11.1 What counts as a defect

Defects: price variance outside tolerance and uncured; quantity shortfall; over-delivery
beyond 5%; tax discrepancy beyond $0.02; unauthorised surcharge; missing goods receipt on a
GOODS PO; unresolvable currency mismatch; suspected duplicate.

**Not** defects: UOM normalisation (clause 2); price variance within tolerance (clause 3);
price variance cured by authorisation (clause 3.1); over-delivery within 5% (clause 4);
contract-rate currency conversion (clause 7); permitted freight within limit (clause 6);
absent goods receipt on a SERVICES PO (clause 1); credit-memo netting (clause 9).

## 12. Dispositions

Exactly one of:

| Disposition | Meaning | `payable_amount` |
| --- | --- | --- |
| `APPROVE_FOR_PAYMENT` | Clean, or all discrepancies resolved in the supplier's favour lawfully | full computed payable |
| `SHORT_PAY` | Pay a reduced, corrected amount | the corrected amount |
| `HOLD_PRICE_VARIANCE` | Do not pay; price/surcharge issue needs buyer action | `0.00` |
| `HOLD_QUANTITY_VARIANCE` | Do not pay; quantity issue needs receiving action | `0.00` |
| `DUPLICATE_REJECT` | Do not pay; already invoiced | `0.00` |
| `ESCALATE_HUMAN` | Clause 11 triggered; reviewer decides | computed recommended payable |

`payable_amount` is the amount released **if** the required approver signs off. It is never
paid automatically.

## 13. Human authority

No disposition in this policy authorises payment. Every case terminates in a review packet
presented to the approver named in clause 10. ClearQueue recommends; a person decides.
