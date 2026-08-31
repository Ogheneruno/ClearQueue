"""The iteration ladder.

Every version of ClearQueue is the same code path with different levers switched on. That
is deliberate: if v2 beats v1, the only thing that changed is the lever named in the row,
so the changelog can attribute the delta honestly. Nothing else is allowed to drift between
arms -- same cases, same policy document, same output schema, same scorer.

Levers
------
``policy``       put policy/ap_policy.md in the system prompt
``schema``       constrain the reply with output_config.format (structured output)
``evidence``     "dump" = every file inlined up front; "tools" = the agent retrieves
``calc_tools``   deterministic calculators from clearqueue/tools.py
``verifier``     a second model pass re-derives the arithmetic and can veto
``memory``       vendor facts carried across the queue
``confidence``   the removal experiment: let the model self-rate and skip verification
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Version:
    name: str
    headline: str
    policy: bool = False
    schema: bool = False
    evidence: str = "dump"          # "dump" | "tools"
    calc_tools: bool = False
    verifier: bool = False
    memory: bool = False
    confidence: bool = False
    hypothesis: str = ""

    def tool_groups(self) -> list[str]:
        groups = []
        if self.calc_tools:
            groups.append("calc")
        if self.evidence == "tools":
            groups.append("evidence")
        if self.memory:
            groups.append("memory")
        return groups

    def levers(self) -> list[str]:
        on = []
        for f in ("policy", "schema", "calc_tools", "verifier", "memory", "confidence"):
            if getattr(self, f):
                on.append(f)
        on.append(f"evidence={self.evidence}")
        return on


VERSIONS: dict[str, Version] = {
    "v0-naive": Version(
        name="v0-naive",
        headline="One-shot prompt. No policy, no schema, evidence dumped in.",
        hypothesis="Establishes the floor. A capable model with the documents but no "
                   "written policy has to invent the tolerances, and will not agree with "
                   "the Controller's Office about what they are.",
    ),
    # v1 is the FAIR BASELINE for the headline comparison: it gets the same policy, the
    # same evidence and the same output contract as the agent. Only scaffolding differs
    # from here on.
    "v1-baseline": Version(
        name="v1-baseline",
        headline="Fair baseline: full policy in context, strict output schema, all evidence "
                 "inlined, single call, no tools.",
        policy=True, schema=True,
        hypothesis="Removes format failures and gives the model the actual rules. This is "
                   "the strongest thing you can build without agent scaffolding, so it is "
                   "what the agent must beat to have proved anything.",
    ),
    "v2-tools": Version(
        name="v2-tools",
        headline="+ deterministic calculators (UOM, tolerance, quantity, tax, FX, credits, "
                 "thresholds).",
        policy=True, schema=True, calc_tools=True,
        hypothesis="Largest expected single gain. The arithmetic leaves the model. Amount "
                   "accuracy should move much more than disposition accuracy -- if both "
                   "move equally, something other than arithmetic was fixed and the claim "
                   "is wrong.",
    ),
    "v3-evidence": Version(
        name="v3-evidence",
        headline="+ evidence retrieval instead of a context dump, with mandatory citation.",
        policy=True, schema=True, calc_tools=True, evidence="tools",
        hypothesis="Cases 005 and 009 turn on one line in an email or a contract that is "
                   "easy to skim past when it arrives inside a wall of inlined text. "
                   "Forcing a deliberate read, and a citation, should fix them.",
    ),
    "v4-verifier": Version(
        name="v4-verifier",
        headline="+ independent verifier pass that re-derives the arithmetic and can veto an "
                 "unreconciled approval.",
        policy=True, schema=True, calc_tools=True, evidence="tools", verifier=True,
        hypothesis="Targets the false-approval rate specifically -- the error that costs "
                   "money. Expected to cost tokens and latency for little accuracy gain.",
    ),
    "v5-memory": Version(
        name="v5-memory",
        headline="+ vendor memory carried across the queue.",
        policy=True, schema=True, calc_tools=True, evidence="tools", verifier=True,
        memory=True,
        hypothesis="A queue is not a set of independent cases. Facts established on an "
                   "earlier invoice -- this vendor bills a monthly retainer, this buyer "
                   "authorised a surcharge -- should carry forward. Risk: a fact that was "
                   "true for one PO gets applied to another where it is not.",
    ),
    # Reported whatever the numbers say. Built to be removed if it behaves as expected.
    "vX-confidence": Version(
        name="vX-confidence",
        headline="REMOVAL EXPERIMENT: model self-rates confidence and skips verification when "
                 "it feels sure.",
        policy=True, schema=True, calc_tools=True, evidence="tools", verifier=True,
        memory=True, confidence=True,
        hypothesis="Cheaper and probably no less accurate on aggregate -- and that is the "
                   "trap. Self-rated confidence is expected to be highest exactly where the "
                   "model is confidently wrong, so false approvals should rise even if "
                   "accuracy does not fall.",
    ),
}

VERSIONS["final"] = Version(
    name="final",
    headline="Shipping configuration: the survivors.",
    policy=True, schema=True, calc_tools=True, evidence="tools", verifier=True, memory=True,
    hypothesis="Whatever survived measurement.",
)

LADDER = ["v0-naive", "v1-baseline", "v2-tools", "v3-evidence", "v4-verifier", "v5-memory"]
