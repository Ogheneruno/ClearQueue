"""Review packets -- the artifact a human actually signs.

Ground rules 04 and 05: nothing consequential happens without a qualified human, and the
human has to be given enough to judge on. A disposition and a number are not enough. The
packet is rebuilt *from the recorded trajectory*, not from the agent's summary of itself,
so a reviewer who distrusts the rationale can read what was actually computed and what was
actually opened.

That direction of dependency matters: if a trajectory were ever too thin to reconstruct the
decision, packet rendering would visibly degrade, rather than the gap going unnoticed.
"""

from __future__ import annotations

import json
from pathlib import Path

from .tools import CALC_SCHEMAS

# The audit section is about arithmetic. Evidence reads and vendor recall are retrieval and
# belong under "Evidence relied on"; listing them under a heading that promises deterministic
# computation would overstate what was actually computed.
CALC_TOOLS = {t["name"] for t in CALC_SCHEMAS}

DISPOSITION_MEANING = {
    "APPROVE_FOR_PAYMENT": "Release for payment on approval.",
    "SHORT_PAY": "Pay the reduced amount below; the balance is disputed.",
    "HOLD_PRICE_VARIANCE": "Do not pay. Buyer action needed on price.",
    "HOLD_QUANTITY_VARIANCE": "Do not pay. Receiving action needed on quantity.",
    "DUPLICATE_REJECT": "Do not pay. Already invoiced.",
    "ESCALATE_HUMAN": "Do not pay. Reviewer decides; the figure below is a recommendation.",
}


def load_trajectory(case_out: Path) -> list[dict]:
    path = case_out / "trajectory.jsonl"
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def render(case_id: str, case_dir: Path, verdict: dict, case_out: Path) -> str:
    events = load_trajectory(case_out)
    meta = verdict.get("_meta", {})
    invoice = json.loads((case_dir / "invoice.json").read_text(encoding="utf-8"))
    po_path = case_dir / "po.json"
    po = json.loads(po_path.read_text(encoding="utf-8")) if po_path.exists() else {}

    disp = verdict.get("disposition") or "NO VERDICT"
    amount = verdict.get("payable_amount")
    amount_s = f"{amount:,.2f}" if isinstance(amount, (int, float)) else "n/a"
    cur = verdict.get("currency", "")

    L: list[str] = []
    L.append(f"# Review packet — {case_id}")
    L.append("")
    L.append(f"**Vendor** {invoice.get('vendor_name_as_billed', '?')}  ")
    L.append(f"**Invoice** {invoice.get('invoice_number', '?')}, dated {invoice.get('invoice_date', '?')}  ")
    L.append(f"**Purchase order** {invoice.get('po_number', '?')} ({po.get('type', 'unknown type')})  ")
    billed = invoice.get("gross_amount")
    billed_s = f"{billed:,.2f}" if isinstance(billed, (int, float)) else str(billed or "?")
    L.append(f"**Billed** {billed_s} {invoice.get('currency', '')}")
    if invoice.get("service_period"):
        L.append(f"  \n**Service period** {invoice['service_period']}")
    L.append("")
    L.append("---")
    L.append("")
    L.append("## Recommendation")
    L.append("")
    L.append(f"| | |")
    L.append(f"|---|---|")
    L.append(f"| **Disposition** | `{disp}` |")
    L.append(f"| **Payable if approved** | **{amount_s} {cur}** |")
    L.append(f"| **Required approver** | `{verdict.get('required_approver_role') or 'n/a'}` |")
    L.append(f"| **Meaning** | {DISPOSITION_MEANING.get(disp, 'No verdict was produced.')} |")
    L.append("")

    defects = verdict.get("defects") or []
    L.append("**Defects found:** " + (", ".join(f"`{d}`" for d in defects) if defects else "none"))
    L.append("")
    if verdict.get("rationale"):
        L.append("**Rationale.** " + verdict["rationale"])
        L.append("")

    cites = verdict.get("citations") or []
    L.append("## Evidence relied on")
    L.append("")
    if cites:
        for c in cites:
            L.append(f"- `{c}`")
    else:
        L.append("- _none cited_")
    read = [f for f in (meta.get("files_read") or []) if f not in cites]
    if read:
        L.append("")
        L.append("Also opened but not cited as decisive: " + ", ".join(f"`{f}`" for f in read))
    L.append("")

    calls = [e for e in events if e.get("type") == "tool_call"]
    results = {e.get("seq"): e for e in events if e.get("type") == "tool_result"}
    calc_calls = [c for c in calls if c.get("tool") in CALC_TOOLS]
    L.append("## Computation audit")
    L.append("")
    if calc_calls:
        L.append("Every figure below came from a deterministic calculator, not from the "
                 "model's arithmetic. Evidence retrieval is listed above, not here.")
        L.append("")
        for c in calc_calls:
            res = results.get(c["seq"] + 1)
            out = res.get("output") if res else None
            L.append(f"- **`{c.get('tool')}`**(`{json.dumps(c.get('input', {}))}`)")
            L.append(f"  → `{_condense(out)}`")
    else:
        L.append("_No calculator was used on this case; the figures are the model's own "
                 "arithmetic._")
    L.append("")

    ver = meta.get("verification")
    if ver:
        L.append("## Independent control check")
        L.append("")
        if ver.get("skipped_on_confidence"):
            L.append("- **Skipped** — the model self-rated its confidence as high.")
        elif ver.get("confirmed"):
            L.append("- Confirmed: the control check re-derived the figures and agreed.")
        else:
            L.append("- **Not confirmed.** Objections raised:")
            for i in ver.get("issues", []):
                L.append(f"  - {i}")
            if "revision_changed_verdict" in ver:
                L.append(f"  - Agent revised its verdict: "
                         f"**{'yes' if ver['revision_changed_verdict'] else 'no'}**")
        L.append("")

    L.append("---")
    L.append("")
    L.append("## Approval")
    L.append("")
    L.append("> ClearQueue has released no funds and cannot. This packet is a recommendation.")
    L.append(f"> It requires sign-off by **{verdict.get('required_approver_role') or 'a reviewer'}** "
             "under policy clause 10 before anything is paid.")
    L.append("")
    L.append("- [ ] Approved as recommended")
    L.append("- [ ] Approved with amendment: ______________________")
    L.append("- [ ] Rejected — returned to AP")
    L.append("")
    L.append(f"Reviewer: ______________________  Date: ____________")
    L.append("")
    n_calls = meta.get("tool_calls", 0)
    L.append(f"<sub>Generated by ClearQueue {meta.get('version', '?')} "
             f"({', '.join(meta.get('levers', []))}) · "
             f"{n_calls} tool call{'' if n_calls == 1 else 's'} · "
             f"trajectory: `{(case_out / 'trajectory.jsonl').as_posix()}`</sub>")
    L.append("")
    return "\n".join(L)


def _condense(out, limit: int = 220) -> str:
    """Tool results are verbose; the packet shows the numbers, not the policy notes."""
    if isinstance(out, dict):
        trimmed = {k: v for k, v in out.items() if k not in ("note", "content", "bands")}
        if "content" in out:
            trimmed["content"] = str(out["content"])[:120] + "…"
        s = json.dumps(trimmed, default=str)
    else:
        s = str(out)
    return s if len(s) <= limit else s[:limit] + "…"


def queue_report(version, results: list[tuple[str, dict]], out_path: Path) -> str:
    """The queue-level view: what a supervisor sees before opening any single packet."""
    rows = []
    total_release = 0.0
    holds = escalations = 0
    for case_id, v in results:
        amt = v.get("payable_amount")
        disp = v.get("disposition") or "NO VERDICT"
        if isinstance(amt, (int, float)):
            total_release += amt
        if disp.startswith("HOLD") or disp == "DUPLICATE_REJECT":
            holds += 1
        if disp == "ESCALATE_HUMAN":
            escalations += 1
        rows.append((case_id, disp, amt, v.get("required_approver_role"),
                     len(v.get("defects") or [])))

    L = [f"# Exception queue — ClearQueue {version.name}", ""]
    L.append(f"{len(results)} exceptions triaged. **Nothing has been paid.** Every line below "
             "is a recommendation awaiting the named approver.")
    L.append("")
    L.append(f"- Recommended for release, pending approval: **{total_release:,.2f}**")
    L.append(f"- Held or rejected: **{holds}**")
    L.append(f"- Escalated to a human decision: **{escalations}**")
    L.append("")
    L.append("| Case | Disposition | Payable if approved | Approver | Defects | Packet |")
    L.append("|---|---|---:|---|---:|---|")
    for cid, disp, amt, role, ndef in rows:
        amt_s = f"{amt:,.2f}" if isinstance(amt, (int, float)) else "—"
        L.append(f"| {cid} | `{disp}` | {amt_s} | {role or '—'} | {ndef} | "
                 f"[packet](packets/{cid}.md) |")
    L.append("")
    L.append("Run `python run.py --review` to step through the queue and record decisions.")
    L.append("")
    text = "\n".join(L)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    return text
