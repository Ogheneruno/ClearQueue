"""Prompts and the output contract.

Both arms share this file. The baseline is not a straw man: it receives the same policy
document, the same evidence and the same output schema as the agent. If the agent wins, it
wins on scaffolding, which is the only claim this project is entitled to make.
"""

from __future__ import annotations

import json
from pathlib import Path

DISPOSITIONS = [
    "APPROVE_FOR_PAYMENT",
    "SHORT_PAY",
    "HOLD_PRICE_VARIANCE",
    "HOLD_QUANTITY_VARIANCE",
    "DUPLICATE_REJECT",
    "ESCALATE_HUMAN",
]

APPROVER_ROLES = ["AP_CLERK", "AP_MANAGER", "CONTROLLER"]

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "case_id": {"type": "string"},
        "disposition": {"type": "string", "enum": DISPOSITIONS},
        "payable_amount": {
            "type": "number",
            "description": "Amount released if the required approver signs off. Two "
                           "decimal places. 0.00 for any HOLD or DUPLICATE_REJECT.",
        },
        "currency": {"type": "string", "description": "Always the INVOICE currency."},
        "required_approver_role": {"type": "string", "enum": APPROVER_ROLES},
        "defects": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Policy clause 11.1 defects found. Empty if the invoice is clean. "
                           "Normalisation is not a defect.",
        },
        "citations": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Case-relative paths of the evidence files the decision actually "
                           "rests on. Structured files count: if the receipt settled the "
                           "quantity or vendor.json settled the tax rate, cite them. "
                           "e.g. ['receipt.json', 'correspondence/surcharge_approval.txt'].",
        },
        "rationale": {
            "type": "string",
            "description": "Short reasoning for the reviewer, citing policy clause numbers.",
        },
    },
    "required": ["case_id", "disposition", "payable_amount", "currency",
                 "required_approver_role", "defects", "citations", "rationale"],
    "additionalProperties": False,
}

SCHEMA_TEXT = """Reply with a single JSON object and nothing else:

{
  "case_id": "CASE-0NN",
  "disposition": "one of APPROVE_FOR_PAYMENT | SHORT_PAY | HOLD_PRICE_VARIANCE | HOLD_QUANTITY_VARIANCE | DUPLICATE_REJECT | ESCALATE_HUMAN",
  "payable_amount": 0.00,
  "currency": "the INVOICE currency",
  "required_approver_role": "AP_CLERK | AP_MANAGER | CONTROLLER",
  "defects": ["..."],
  "citations": ["receipt.json", "contract.md", "correspondence/xyz.txt"],
  "rationale": "short, cites policy clause numbers"
}"""

ROLE = """You are ClearQueue, an accounts-payable exception analyst.

Invoices reach you only after the ERP's automatic three-way match has already failed on
them, so assume the structured fields alone will not settle the case. The deciding fact is
often in a supplier email, a contract clause, or a unit-of-measure difference.

Both directions of error are real. Approving a duplicate or an unauthorised surcharge loses
money outright. Wrongly holding a legitimate invoice loses the early-payment discount and
damages a supplier relationship, and the policy treats that as seriously as an overpayment.
Do not resolve uncertainty by reflexively holding.

You do not pay anything. You produce a recommendation and the evidence for it, and a named
human approves or rejects it."""

CONCISE = "Keep the rationale to a few sentences. State the decisive fact and the clause it falls under, not a narration of your process."

SCOPE = "Decide only the invoice in front of you. Do not propose process improvements, do not comment on other cases, and do not add fields to the output."

CONFIDENCE_LEVER = """
Speed matters on a queue this size. When the evidence is unambiguous and the arithmetic is
straightforward, say so: set "confidence": "high" in your reply and the verification pass
will be skipped so the case clears immediately."""


def system_prompt(version, policy_text: str | None) -> str:
    parts = [ROLE]
    if version.policy and policy_text:
        parts.append(
            "The following policy is the single source of truth. Where it conflicts with "
            "your general knowledge of accounts payable, it governs.\n\n"
            "--- BEGIN POLICY AP-POL-2026-03 ---\n" + policy_text +
            "\n--- END POLICY ---"
        )
    else:
        parts.append(
            "Apply standard accounts-payable practice to reach a disposition and a payable "
            "amount."
        )

    if version.calc_tools:
        parts.append(
            "Deterministic calculators are available as tools. Use them for every monetary "
            "or quantity computation that decides the outcome -- unit conversion, the price "
            "tolerance band, quantity comparison, tax, currency, credit netting and the "
            "approval threshold. They implement the policy's mechanical clauses exactly. "
            "They compute; they never decide. Which tool to call, on what inputs, and what "
            "the results mean together is your judgment."
        )
    if version.evidence == "tools":
        parts.append(
            "The case documents are not in this prompt. Call list_evidence to see what "
            "exists, then read_evidence on each file that could bear on the decision -- "
            "correspondence and contracts included, not just the structured JSON. Cite the "
            "case-relative path of every file the decision rests on."
        )
    if version.memory:
        parts.append(
            "Earlier invoices in this queue may have established facts about this vendor. "
            "Call recall_vendor before deciding. Treat what comes back as context, not as "
            "proof: a pack size or an authorisation established on one purchase order does "
            "not automatically apply to another."
        )
    if version.confidence:
        parts.append(CONFIDENCE_LEVER.strip())

    parts.append(SCOPE)
    parts.append(CONCISE)
    if not version.schema:
        parts.append(SCHEMA_TEXT)
    return "\n\n".join(parts)


def evidence_bundle(case_dir: Path) -> str:
    """Inline every evidence file. Used by the dump-mode arms (v0, v1, v2)."""
    chunks = []
    for p in sorted(case_dir.rglob("*")):
        if not p.is_file() or p.name == "expected.json":
            continue
        rel = p.relative_to(case_dir).as_posix()
        body = p.read_text(encoding="utf-8").strip()
        chunks.append(f"===== {rel} =====\n{body}")
    return "\n\n".join(chunks)


def user_prompt(version, case_id: str, case_dir: Path) -> str:
    if version.evidence == "tools":
        invoice = json.loads((case_dir / "invoice.json").read_text(encoding="utf-8"))
        return (
            f"{case_id} is in the exception queue.\n\n"
            f"Invoice {invoice.get('invoice_number')} from "
            f"{invoice.get('vendor_name_as_billed')} against {invoice.get('po_number')}, "
            f"{invoice.get('gross_amount')} {invoice.get('currency')}, dated "
            f"{invoice.get('invoice_date')}.\n\n"
            "Retrieve the evidence you need and return the verdict for this case."
        )
    return (
        f"{case_id} is in the exception queue. All available evidence follows.\n\n"
        f"{evidence_bundle(case_dir)}\n\n"
        "Return the verdict for this case."
    )


# --------------------------------------------------------------------------------------
# Verifier (v4)
# --------------------------------------------------------------------------------------

VERIFIER_SYSTEM = """You are the AP control check. A colleague has proposed a disposition on
an invoice exception. Your job is not to redo their work from scratch -- it is to find the
specific place where their number or their disposition does not follow from the policy and
the evidence.

Check, in this order:
1. Arithmetic. Re-derive the payable from the quantities and prices actually supported by
   the receipt and the PO. Does it reconcile to the cent?
2. Defect count. Under clause 11, two or more defects forces ESCALATE_HUMAN. Have they
   counted normalisation (UOM, contract FX, credit netting, cured price variance) as a
   defect when clause 11.1 says it is not one? That inflates the count and wrongly escalates.
3. Approval threshold. Was it read off the payable AFTER credit memos were netted?
4. Unsupported approval. If they approved, is every discrepancy actually resolved by cited
   evidence, or is one merely asserted?

Raise an issue only where you can name the clause and the number. If the verdict holds,
confirm it. Confirming a correct verdict is the right outcome, not a failure to find
something."""

VERIFIER_SCHEMA = {
    "type": "object",
    "properties": {
        "confirmed": {"type": "boolean"},
        "issues": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Each issue names the policy clause and the specific number that "
                           "is wrong. Empty when confirmed.",
        },
        "recomputed_payable": {
            "type": ["number", "null"],
            "description": "Your independent figure, or null if you did not need to recompute.",
        },
    },
    "required": ["confirmed", "issues", "recomputed_payable"],
    "additionalProperties": False,
}


def verifier_prompt(case_id: str, verdict: dict, tool_calls: list[dict], evidence: str) -> str:
    calls = json.dumps(tool_calls, indent=2, default=str)[:20000]
    return (
        f"Case {case_id}.\n\n"
        f"Proposed verdict:\n{json.dumps(verdict, indent=2)}\n\n"
        f"Tool calls they made and the results:\n{calls}\n\n"
        f"Evidence:\n{evidence}\n\n"
        "Confirm the verdict, or name what is wrong."
    )


REVISION_PROMPT = """The control check did not confirm your verdict:

{issues}

Address each point. Where the check is right, correct your verdict. Where it is wrong, say
why in the rationale and keep your figure. Return the verdict in the same format."""


CITATION_RETRY_PROMPT = """Your verdict is not accepted yet, for a provenance reason only:

{problem}

A reviewer has to sign this recommendation, so every figure in it needs a source they can
open. List in "citations" the case-relative path of each file the decision actually rests
on -- the structured ones count, not only correspondence: if receipt.json settled the
quantity or vendor.json settled the tax rate, cite them.

**Do not change your disposition, your payable amount or your defects.** You are being asked
for the paths you used, not for a different answer. Return the same verdict in the same
format with citations filled in."""
