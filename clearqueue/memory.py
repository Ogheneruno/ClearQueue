"""Vendor memory carried across the queue (the v5 lever).

An exception queue is not a set of independent cases. By the time an AP clerk reaches the
fourth Kestrel invoice of the week they know how Kestrel packs a case and which buyer signs
their surcharges. A stateless agent re-derives that from nothing, every time.

What is stored is deliberately narrow: facts observed on a specific purchase order, always
tagged with the case and PO they came from. Recall returns them as *prior context*, never as
a conclusion -- a pack size that was true for PO-4402 is not evidence about PO-4414, and the
prompt says so explicitly. Memory that generalises silently is worse than no memory, because
it is confidently wrong and leaves no trace of why.
"""

from __future__ import annotations

import json
from pathlib import Path

from .tools import normalize_vendor_name


class VendorMemory:
    """Append-only JSONL store, keyed on the normalised vendor name."""

    def __init__(self, path: Path, enabled: bool = True):
        self.path = Path(path)
        self.enabled = enabled
        self.records: list[dict] = []
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self.records.append(json.loads(line))

    def reset(self) -> None:
        """Each scored run starts from an empty memory, so a run is reproducible on its own."""
        self.records = []
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")

    def observe(self, case_id: str, case: dict, verdict: dict) -> None:
        if not self.enabled:
            return
        vendor = case.get("vendor", {})
        invoice = case.get("invoice", {})
        po = case.get("po", {})
        vendor_name = vendor.get("name") or invoice.get("vendor_name_as_billed") or ""
        record = {
            "case_id": case_id,
            "vendor_name": vendor_name,
            "vendor_key": normalize_vendor_name(vendor_name),
            "po_number": po.get("po_number") or invoice.get("po_number"),
            "po_type": po.get("type"),
            "pack_sizes": vendor.get("pack_sizes") or {},
            "tax_rate": vendor.get("tax_rate"),
            "authorised_buyers": vendor.get("authorised_buyers") or [],
            "service_period": invoice.get("service_period"),
            "disposition": verdict.get("disposition"),
            "defects": verdict.get("defects") or [],
        }
        self.records.append(record)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def recall(self, vendor_name: str) -> dict:
        key = normalize_vendor_name(vendor_name)
        hits = [r for r in self.records if r.get("vendor_key") == key]
        if not hits:
            return {
                "vendor": vendor_name,
                "prior_cases": [],
                "note": "No earlier invoice from this vendor has been processed in this queue.",
            }
        recurring = [r for r in hits if r.get("service_period")]
        return {
            "vendor": vendor_name,
            "prior_cases": [
                {
                    "case_id": r["case_id"],
                    "po_number": r["po_number"],
                    "po_type": r.get("po_type"),
                    "pack_sizes": r.get("pack_sizes"),
                    "authorised_buyers": r.get("authorised_buyers"),
                    "service_period": r.get("service_period"),
                    "disposition": r["disposition"],
                    "defects": r["defects"],
                }
                for r in hits
            ],
            "bills_by_service_period": bool(recurring),
            "note": "Prior context only. Pack sizes, authorisations and billing patterns are "
                    "recorded against the specific purchase order shown; confirm them against "
                    "this case's own vendor.json and correspondence before relying on them.",
        }
