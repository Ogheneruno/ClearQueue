"""Endpoint probe: does this credential support what the ladder actually needs?

Run this before spending on a full ladder. It is not a ping -- it exercises each API
feature ClearQueue depends on, one small call each, and reports which ones the configured
endpoint accepts:

  1. plain message               the baseline arms (v0, v1)
  2. tool use                    the calculators (v2+)
  3. structured output           the strict verdict schema (v1+)
  4. prompt caching              the cost lever on the policy document
  5. tools + schema together     what v2-v5 actually send

A proxy can accept (1) and reject (3), which would fail every scored run halfway through.
Finding that out for a few hundred tokens is much cheaper than finding it out after an hour.
"""

from __future__ import annotations

import json
from pathlib import Path

from .llm import AnthropicClient, LLMError

PROBE_TOOL = {
    "name": "add_numbers",
    "description": "Add two numbers. Use this rather than computing the sum yourself.",
    "input_schema": {
        "type": "object",
        "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
        "required": ["a", "b"],
        "additionalProperties": False,
    },
}

PROBE_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}

# Long enough to be a realistic cache breakpoint; caching has a minimum prefix length.
FILLER = ("This is padding to reach the prompt-caching minimum prefix length. " * 240)


def _body(system, user, **extra) -> dict:
    return {
        "max_tokens": 1024,
        "system": system,
        "messages": [{"role": "user", "content": user}],
        "thinking": {"type": "adaptive", "display": "summarized"},
        "output_config": {"effort": "low"},
        **extra,
    }


def probe(model: str = "claude-opus-5", repo_root: Path | None = None) -> int:
    try:
        client = AnthropicClient(model=model, repo_root=repo_root)
    except LLMError as e:
        print(f"\n{e}\n")
        return 2

    print(f"\nEndpoint probe")
    print(f"  credential : {client.credential_source}")
    print(f"  model      : {model}")
    if not client.portable:
        print("  NOTE       : this endpoint is not api.anthropic.com. Traces produced here")
        print("               are still valid, but a judge cannot reproduce against it --")
        print("               they use `python score.py --replay runs/recorded` instead.")
    print()

    checks: list[tuple[str, str, dict]] = [
        ("plain message", "v0/v1 baseline arms",
         _body("Reply with exactly: OK", "Say OK.")),
        ("tool use", "v2+ deterministic calculators",
         _body("Use the provided tool for any arithmetic.",
               "What is 17 plus 25? Use the tool.", tools=[PROBE_TOOL])),
        ("structured output", "v1+ strict verdict schema",
         _body("Answer the question.", "What colour is a clear sky at noon?",
               output_config={"effort": "low",
                              "format": {"type": "json_schema", "schema": PROBE_SCHEMA}})),
        ("prompt caching", "the cost lever on the policy document",
         _body([{"type": "text", "text": FILLER,
                 "cache_control": {"type": "ephemeral"}}], "Say OK.")),
        ("tools + schema", "exactly what v2-v5 send",
         _body("Use the tool, then answer.", "What is 3 plus 4? Use the tool.",
               tools=[PROBE_TOOL],
               output_config={"effort": "low",
                              "format": {"type": "json_schema", "schema": PROBE_SCHEMA}})),
    ]

    width = max(len(n) for n, _, _ in checks)
    failures = 0
    results = []

    for name, why, body in checks:
        body = {"model": model, **body}
        try:
            resp = client._post("/v1/messages", body)
            detail = _describe(name, resp)
            print(f"  PASS  {name.ljust(width)}   {detail}")
            results.append((name, True, detail))
        except LLMError as e:
            msg = str(e).split("\n")[0][:160]
            print(f"  FAIL  {name.ljust(width)}   {msg}")
            print(f"        {'':<{width}}   needed for: {why}")
            results.append((name, False, msg))
            failures += 1

    print()
    if failures == 0:
        print("  All five features are supported. The full ladder can run against this")
        print("  endpoint. Next: python run.py --ladder --llm anthropic")
        return 0

    print(f"  {failures} of {len(checks)} features unsupported on this endpoint.")
    print("  Stopping here rather than starting a ladder that would fail partway.")
    print("  Options: use a personal key (copy .env.example to .env.local), or reduce the")
    print("  ladder to the versions whose features passed.")
    return 1


def _describe(name: str, resp: dict) -> str:
    usage = resp.get("usage", {}) or {}
    stop = resp.get("stop_reason")
    bits = [f"stop={stop}"]

    if name == "tool use":
        used = [b.get("name") for b in resp.get("content", []) if b.get("type") == "tool_use"]
        bits.append(f"tool_use={used or 'NONE RETURNED'}")
    if name == "structured output":
        text = "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")
        try:
            json.loads(text)
            bits.append("valid JSON")
        except json.JSONDecodeError:
            bits.append("NOT valid JSON")
    if name == "prompt caching":
        wrote = usage.get("cache_creation_input_tokens", 0)
        read = usage.get("cache_read_input_tokens", 0)
        bits.append(f"cache write={wrote} read={read}")
        if not wrote and not read:
            bits.append("(no cache activity — caching may be ignored here)")

    bits.append(f"in={usage.get('input_tokens', 0)} out={usage.get('output_tokens', 0)}")
    return "  ".join(bits)
