"""The solver. One code path for every arm; the version's levers are the only difference.

There is no separate `baseline.py` and `agent.py` on purpose. If the baseline lived in its
own file it would drift -- a slightly different prompt here, a missing document there -- and
the comparison would quietly stop being fair. Here the baseline is literally the agent with
its scaffolding switched off, so the measured delta is attributable to the scaffolding and
nothing else.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import prompts
from .llm import Recorder, Usage, extract_json, run_conversation
from .prompts import VERDICT_SCHEMA, VERIFIER_SCHEMA
from .tools import ToolBox, approver_for, money, schemas_for

VALID_DISPOSITIONS = set(prompts.DISPOSITIONS)
ZERO_PAYABLE = {"HOLD_PRICE_VARIANCE", "HOLD_QUANTITY_VARIANCE", "DUPLICATE_REJECT"}


def verdict_schema_for(version) -> dict:
    """The confidence lever needs an extra field, so the schema is built per version."""
    if not version.confidence:
        return VERDICT_SCHEMA
    schema = json.loads(json.dumps(VERDICT_SCHEMA))
    schema["properties"]["confidence"] = {
        "type": "string",
        "enum": ["high", "medium", "low"],
        "description": "How sure you are. 'high' skips the verification pass.",
    }
    schema["required"].append("confidence")
    return schema


def load_case(case_dir: Path) -> dict:
    out = {}
    for name in ("po", "receipt", "invoice", "vendor"):
        p = case_dir / f"{name}.json"
        out[name] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    return out


def solve_case(
    case_id: str,
    case_dir: Path,
    version,
    client,
    policy_text: str,
    out_dir: Path,
    memory=None,
) -> dict:
    """Produce one verdict, with its trajectory written alongside."""
    out_dir.mkdir(parents=True, exist_ok=True)
    recorder = Recorder(out_dir / "trajectory.jsonl")
    recorder.log("case_start", case_id=case_id, version=version.name, levers=version.levers())

    toolbox = ToolBox(case_dir, memory=memory if version.memory else None)
    tool_groups = version.tool_groups()
    tools = schemas_for(*tool_groups) if tool_groups else None
    schema = verdict_schema_for(version) if version.schema else None

    system = prompts.system_prompt(version, policy_text)
    user = prompts.user_prompt(version, case_id, case_dir)
    usage = Usage()

    result = run_conversation(
        client,
        system=system,
        user_prompt=user,
        tools=tools,
        dispatch=toolbox.dispatch,
        json_schema=schema,
        recorder=recorder,
        usage=usage,
    )

    verdict = extract_json(result.text)
    parse_failed = verdict is None
    if parse_failed:
        recorder.log("parse_failure", text=result.text[:2000])

    verification = None
    if version.verifier and verdict is not None:
        skipped = version.confidence and str(verdict.get("confidence", "")).lower() == "high"
        if skipped:
            recorder.log("verification_skipped", reason="model self-rated confidence high")
            verification = {"confirmed": True, "issues": [], "skipped_on_confidence": True}
        else:
            verdict, verification = _verify(
                client, case_id, case_dir, version, verdict, toolbox, result,
                system, schema, recorder, usage,
            )

    verdict = _normalise(verdict, case_id, case_dir, toolbox)
    verdict["_meta"] = {
        **usage.as_meta(getattr(client, "model", "unknown")),
        "version": version.name,
        "levers": version.levers(),
        "turns": result.turns,
        "stop_reason": result.stop_reason,
        "parse_failure": parse_failed,
        "refused": result.refused,
        "files_read": list(toolbox.cited),
        "verification": verification,
    }

    recorder.log("verdict", **{k: v for k, v in verdict.items() if k != "_meta"})
    (out_dir / "verdict.json").write_text(
        json.dumps(verdict, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return verdict


def _verify(client, case_id, case_dir, version, verdict, toolbox, result,
            system, schema, recorder, usage):
    """Independent second pass. On a non-confirmation the agent gets one revision turn.

    The verifier's number is never written straight into the verdict. It raises objections;
    the agent -- which still has its tool history -- answers them. A verifier that could
    overwrite the answer would just be a second guess with extra steps, and would sometimes
    overwrite a correct figure with a worse one.
    """
    evidence = prompts.evidence_bundle(case_dir)
    v_prompt = prompts.verifier_prompt(case_id, verdict, toolbox.calls, evidence)
    recorder.log("verifier_call", case_id=case_id)

    v_result = run_conversation(
        client,
        system=prompts.VERIFIER_SYSTEM,
        user_prompt=v_prompt,
        json_schema=VERIFIER_SCHEMA if version.schema else None,
        recorder=None,
        usage=usage,
    )
    check = extract_json(v_result.text) or {"confirmed": True, "issues": []}
    recorder.log("verifier_result", **check)

    if check.get("confirmed") or not check.get("issues"):
        return verdict, check

    issues = "\n".join(f"- {i}" for i in check["issues"])
    recorder.log("revision_requested", issues=check["issues"])
    revised = run_conversation(
        client,
        system=system,
        messages=result.messages + [
            {"role": "user", "content": prompts.REVISION_PROMPT.format(issues=issues)}
        ],
        tools=schemas_for(*version.tool_groups()) if version.tool_groups() else None,
        dispatch=toolbox.dispatch,
        json_schema=schema,
        recorder=recorder,
        usage=usage,
    )
    new_verdict = extract_json(revised.text)
    if new_verdict is None:
        recorder.log("revision_unparseable", text=revised.text[:1000])
        return verdict, {**check, "revision_failed": True}

    changed = (
        new_verdict.get("disposition") != verdict.get("disposition")
        or new_verdict.get("payable_amount") != verdict.get("payable_amount")
    )
    recorder.log("revision_applied", changed=changed,
                 before={"disposition": verdict.get("disposition"),
                         "payable_amount": verdict.get("payable_amount")},
                 after={"disposition": new_verdict.get("disposition"),
                        "payable_amount": new_verdict.get("payable_amount")})
    return new_verdict, {**check, "revision_changed_verdict": changed}


def _normalise(verdict: dict | None, case_id: str, case_dir: Path, toolbox: ToolBox) -> dict:
    """Coerce the reply into the scorer's shape without inventing an answer.

    Repairs are limited to type coercion and the policy's own hard invariants. Nothing here
    guesses a disposition or an amount: an unusable reply stays unusable and is scored as
    the miss it is. Citations in particular are only ever what the model declared -- the
    files it happened to open are recorded separately in _meta, because crediting a citation
    for merely reading a file would make the citation metric measure nothing.
    """
    invoice = json.loads((case_dir / "invoice.json").read_text(encoding="utf-8"))

    if not isinstance(verdict, dict):
        return {
            "case_id": case_id,
            "disposition": None,
            "payable_amount": None,
            "currency": invoice.get("currency", "USD"),
            "required_approver_role": None,
            "defects": [],
            "citations": [],
            "rationale": "No parseable verdict was produced.",
        }

    out = dict(verdict)
    out["case_id"] = case_id

    disp = out.get("disposition")
    out["disposition"] = disp if disp in VALID_DISPOSITIONS else None

    try:
        out["payable_amount"] = money(out.get("payable_amount"))
    except Exception:
        out["payable_amount"] = None

    # Policy clause 12: a hold or a duplicate rejection releases nothing. This is an
    # invariant of the disposition itself, not a judgment call, so it is enforced here.
    if out["disposition"] in ZERO_PAYABLE:
        out["payable_amount"] = 0.00

    out.setdefault("currency", invoice.get("currency", "USD"))
    out["defects"] = [str(d) for d in (out.get("defects") or [])]
    out["citations"] = [
        str(c).replace("\\", "/").strip().lstrip("./") for c in (out.get("citations") or [])
    ]
    out.setdefault("rationale", "")

    if out.get("required_approver_role") not in ("AP_CLERK", "AP_MANAGER", "CONTROLLER"):
        # Clause 10 is a lookup table, not a decision. If the model omitted it we derive it
        # rather than scoring a blank, so the approver metric measures the amount and not
        # the model's willingness to fill in a field.
        out["required_approver_role"] = (
            approver_for(out["payable_amount"]) if out["payable_amount"] is not None else None
        )
    return out
