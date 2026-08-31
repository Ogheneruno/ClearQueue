"""Anthropic Messages API client, deterministic mock, and trajectory recorder.

Zero third-party dependencies. The API is reached with stdlib ``urllib.request`` so a
judge needs nothing but Python 3.11+ to reproduce this project -- no ``pip install``,
no lockfile, no virtualenv drift.

Three things live here:

``AnthropicClient``   real Messages API over raw HTTP, with retries and usage accounting.
``MockLLM``           scripted, deterministic, free. Validates the harness without a key.
``Recorder``          writes runs/<arm>/<case>/trajectory.jsonl -- the audit trail.

The tool loop (``run_conversation``) is shared by both arms so the only difference
between the baseline and the agent is the tools and prompts they are given, never the
plumbing.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-opus-5"
DEFAULT_MAX_TOKENS = 16000

# USD per million tokens, list price. Used only for reporting cost per case.
PRICING = {
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
}
CACHE_READ_MULTIPLIER = 0.1
CACHE_WRITE_MULTIPLIER = 1.25


class LLMError(RuntimeError):
    """Any failure to obtain a usable response."""


class AuthError(LLMError):
    """No credential, or the credential was rejected."""


# --------------------------------------------------------------------------------------
# Usage accounting
# --------------------------------------------------------------------------------------

@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    api_calls: int = 0
    tool_calls: int = 0
    latency_s: float = 0.0

    def add_response(self, body: dict) -> None:
        u = body.get("usage") or {}
        self.input_tokens += u.get("input_tokens", 0) or 0
        self.output_tokens += u.get("output_tokens", 0) or 0
        self.cache_read_input_tokens += u.get("cache_read_input_tokens", 0) or 0
        self.cache_creation_input_tokens += u.get("cache_creation_input_tokens", 0) or 0
        self.api_calls += 1

    def cost_usd(self, model: str) -> float:
        in_rate, out_rate = PRICING.get(model, (0.0, 0.0))
        billable_in = (
            self.input_tokens
            + self.cache_read_input_tokens * CACHE_READ_MULTIPLIER
            + self.cache_creation_input_tokens * CACHE_WRITE_MULTIPLIER
        )
        return (billable_in * in_rate + self.output_tokens * out_rate) / 1_000_000

    def as_meta(self, model: str) -> dict:
        return {
            "model": model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
            "api_calls": self.api_calls,
            "tool_calls": self.tool_calls,
            "latency_s": round(self.latency_s, 2),
            "cost_usd": round(self.cost_usd(model), 6),
        }


# --------------------------------------------------------------------------------------
# Trajectory recorder
# --------------------------------------------------------------------------------------

class Recorder:
    """Append-only JSONL trace: every instruction, tool call, tool result and verdict.

    This is a required hackathon deliverable, but it is also how we debug: when a case
    regresses between iterations, the diff between two trajectories shows exactly which
    tool call or which piece of evidence changed the outcome.
    """

    def __init__(self, path: Path | None):
        self.path = path
        self.events: list[dict] = []
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")

    def log(self, event_type: str, **payload: Any) -> None:
        event = {"seq": len(self.events), "type": event_type, **payload}
        self.events.append(event)
        if self.path is not None:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")


# --------------------------------------------------------------------------------------
# Real client
# --------------------------------------------------------------------------------------

DEFAULT_ENDPOINT = "https://api.anthropic.com"
ENV_FILE = "\x2eenv.local"


def load_env_file(path: Path) -> dict[str, str]:
    """Read a KEY=value file. Never printed, never committed -- see .gitignore."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        values[key.strip()] = val.strip().strip('"').strip("'")
    return values


@dataclass
class Credential:
    headers: dict[str, str]
    base_url: str
    source: str          # human-readable, safe to print
    portable: bool       # can a judge reproduce against this endpoint?


def resolve_credential(repo_root: Path | None = None) -> Credential:
    """Pick a credential and an endpoint, and say out loud which one was used.

    Order: a personal key in .env.local, then a personal key in the environment, then an
    ambient auth token (this machine's Claude Code session proxy).

    One rule is enforced rather than left to care: **a personal API key is never sent to a
    base URL it did not come with.** The ambient ANTHROPIC_BASE_URL on this machine points
    at a local session proxy; silently posting a personal key there would leak it to a
    process that has no business holding it. A key from .env.local goes to
    api.anthropic.com unless that same file names a different endpoint.

    Nothing here ever logs or persists the secret itself (ground rule 08).
    """
    root = Path(repo_root) if repo_root else Path.cwd()
    local = load_env_file(root / ENV_FILE)

    if local.get("ANTHROPIC_API_KEY"):
        base = (local.get("ANTHROPIC_BASE_URL") or DEFAULT_ENDPOINT).rstrip("/")
        return Credential(
            {"x-api-key": local["ANTHROPIC_API_KEY"]}, base,
            f"personal API key from {ENV_FILE} -> {base}",
            portable=base == DEFAULT_ENDPOINT,
        )

    if os.environ.get("ANTHROPIC_API_KEY"):
        base = (os.environ.get("ANTHROPIC_BASE_URL") or DEFAULT_ENDPOINT).rstrip("/")
        return Credential(
            {"x-api-key": os.environ["ANTHROPIC_API_KEY"]}, base,
            f"ANTHROPIC_API_KEY from the environment -> {base}",
            portable=base == DEFAULT_ENDPOINT,
        )

    token = os.environ.get("ANTHROPIC_AUTH_TOKEN")
    if token:
        base = (os.environ.get("ANTHROPIC_BASE_URL") or DEFAULT_ENDPOINT).rstrip("/")
        # Bearer tokens go on Authorization, never on x-api-key, and /v1/messages
        # requires the oauth beta header.
        return Credential(
            {"Authorization": f"Bearer {token}", "anthropic-beta": "oauth-2025-04-20"},
            base,
            f"ambient ANTHROPIC_AUTH_TOKEN -> {base}",
            portable=base == DEFAULT_ENDPOINT,
        )

    raise AuthError(
        f"No credential found.\n\n"
        f"To run live, copy .env.example to {ENV_FILE} and put a key in it:\n"
        f"    ANTHROPIC_API_KEY=sk-ant-...\n\n"
        "Or set ANTHROPIC_API_KEY in your environment.\n\n"
        "No key? Everything except the live runs works offline:\n"
        "    python verify.py                       full check, no credential\n"
        "    python run.py --llm mock               harness smoke test\n"
        "    python score.py --replay runs/recorded reproduce our headline numbers"
    )


class AnthropicClient:
    """Messages API over stdlib urllib.

    Deliberately not the SDK: this keeps the project at zero install steps, which is
    worth more here than the SDK's conveniences.
    """

    name = "anthropic"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        effort: str = "high",
        thinking: bool = True,
        cache: bool = True,
        timeout: float = 600.0,
        max_retries: int = 4,
        repo_root: Path | None = None,
    ):
        self.model = model
        self.max_tokens = max_tokens
        self.effort = effort
        self.thinking = thinking
        self.cache = cache
        self.timeout = timeout
        self.max_retries = max_retries
        cred = resolve_credential(repo_root)
        self._headers, self._base = cred.headers, cred.base_url
        self.credential_source = cred.source
        self.portable = cred.portable

    def create(
        self,
        *,
        system: str | list,
        messages: list[dict],
        tools: list[dict] | None = None,
        json_schema: dict | None = None,
    ) -> dict:
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": self._system_blocks(system),
            "messages": messages,
            # Summarised thinking makes the trajectory readable to a human reviewer.
            # (On claude-opus-5 thinking is on by default but its text is omitted.)
            "thinking": {"type": "adaptive", "display": "summarized"},
            "output_config": {"effort": self.effort},
        }
        if not self.thinking:
            # Only legal at effort high or below; the caller is responsible for that.
            body["thinking"] = {"type": "disabled"}
        if tools:
            body["tools"] = self._cached_tools(tools)
        if json_schema:
            body["output_config"]["format"] = {"type": "json_schema", "schema": json_schema}
        return self._post("/v1/messages", body)

    def _system_blocks(self, system: str | list):
        """Cache the system prompt.

        The policy document is ~3,200 tokens and is byte-identical on all 14 cases, so
        without caching we would pay full input price for it 14 times per run and again on
        every tool turn. One cache breakpoint here is the single largest cost lever in the
        project.
        """
        if not self.cache or not isinstance(system, str):
            return system
        return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]

    def _cached_tools(self, tools: list[dict]) -> list[dict]:
        """A breakpoint on the last tool definition caches the whole schema block."""
        if not self.cache:
            return tools
        cached = [dict(t) for t in tools]
        cached[-1]["cache_control"] = {"type": "ephemeral"}
        return cached

    def _post(self, path: str, body: dict) -> dict:
        data = json.dumps(body).encode("utf-8")
        headers = {
            "content-type": "application/json",
            "anthropic-version": API_VERSION,
            **self._headers,
        }
        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            req = urllib.request.Request(self._base + path, data=data, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:600]
                if e.code in (401, 403):
                    raise AuthError(f"HTTP {e.code} from the API: {detail}") from e
                if e.code in (408, 409, 429) or e.code >= 500:
                    last = LLMError(f"HTTP {e.code}: {detail}")
                    delay = _retry_after(e) or min(30.0, 2.0 ** attempt)
                else:
                    raise LLMError(f"HTTP {e.code}: {detail}") from e
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last = LLMError(f"connection error: {e}")
                delay = min(30.0, 2.0 ** attempt)
            if attempt < self.max_retries:
                time.sleep(delay)
        raise last or LLMError("request failed with no diagnostic")


def _retry_after(e: urllib.error.HTTPError) -> float | None:
    try:
        return float(e.headers.get("retry-after"))
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------------------
# Deterministic mock
# --------------------------------------------------------------------------------------

class MockLLM:
    """A scripted stand-in that makes the harness testable with no credential and no cost.

    It is NOT a model and makes no attempt to be right. Its job is to prove the
    scaffolding works: that tools are dispatched, results are fed back, the verdict is
    parsed, the packet renders, and the scorer runs end to end.

    Its default policy is deliberately the always-approve control strategy, so a mock
    run must land on exactly the control's score. If it does not, the harness -- not the
    model -- is broken.
    """

    name = "mock"

    def __init__(self, model: str = "mock", responder: Callable[[str], dict] | None = None):
        self.model = model
        self.responder = responder
        self._turns: dict[int, int] = {}

    def create(
        self,
        *,
        system: str | list,
        messages: list[dict],
        tools: list[dict] | None = None,
        json_schema: dict | None = None,
    ) -> dict:
        case_id = _find_case_id(messages) or "UNKNOWN"
        turn = sum(1 for m in messages if m["role"] == "assistant")

        # The verifier pass. The mock always confirms: it is not judging anything, it is
        # proving the second call is wired up and its result flows back.
        if isinstance(system, str) and "AP control check" in system:
            return _mock_response([{
                "type": "text",
                "text": json.dumps({"confirmed": True, "issues": [], "recomputed_payable": None}),
            }])

        # On the first turn, if evidence tools exist, exercise one so the loop is tested.
        if turn == 0 and tools:
            names = {t["name"] for t in tools}
            if "read_evidence" in names:
                return _mock_response(
                    [{
                        "type": "tool_use",
                        "id": f"toolu_mock_{case_id}_0",
                        "name": "read_evidence",
                        "input": {"path": "invoice.json"},
                    }],
                    stop_reason="tool_use",
                )

        verdict = self.responder(case_id) if self.responder else {
            "case_id": case_id,
            "disposition": "APPROVE_FOR_PAYMENT",
            "payable_amount": 0.0,
            "currency": "USD",
            "required_approver_role": "AP_CLERK",
            "citations": [],
            "rationale": "mock: no evidence was actually read",
        }
        return _mock_response([{"type": "text", "text": json.dumps(verdict, indent=2)}])


def _mock_response(content: list[dict], stop_reason: str = "end_turn") -> dict:
    return {
        "id": "msg_mock",
        "type": "message",
        "role": "assistant",
        "model": "mock",
        "content": content,
        "stop_reason": stop_reason,
        "usage": {"input_tokens": 0, "output_tokens": 0},
    }


def _find_case_id(messages: list[dict]) -> str | None:
    for m in messages:
        content = m.get("content")
        text = content if isinstance(content, str) else " ".join(
            b.get("text", "") for b in content if isinstance(b, dict)
        )
        idx = text.find("CASE-")
        if idx != -1:
            return text[idx:idx + 8]
    return None


# --------------------------------------------------------------------------------------
# Shared tool loop
# --------------------------------------------------------------------------------------

@dataclass
class ConversationResult:
    text: str
    usage: Usage
    stop_reason: str
    turns: int
    tool_log: list[dict] = field(default_factory=list)
    refused: bool = False
    messages: list[dict] = field(default_factory=list)


def run_conversation(
    client,
    *,
    system: str | list,
    user_prompt: str | None = None,
    messages: list[dict] | None = None,
    tools: list[dict] | None = None,
    dispatch: Callable[[str, dict], Any] | None = None,
    json_schema: dict | None = None,
    recorder: Recorder | None = None,
    usage: Usage | None = None,
    max_turns: int = 14,
) -> ConversationResult:
    """Drive the request -> tool_use -> tool_result loop until the model stops calling tools.

    Written as an explicit loop rather than an SDK helper so that every step is visible
    in the trajectory: this project's evidence claims rest on those traces.

    Pass ``messages`` instead of ``user_prompt`` to continue an existing conversation --
    that is how the v4 verifier's objections go back to the agent with its tool history
    intact, rather than as a fresh call that has forgotten what it already computed.
    """
    if messages is None:
        if user_prompt is None:
            raise ValueError("supply either user_prompt or messages")
        messages = [{"role": "user", "content": user_prompt}]
    else:
        messages = list(messages)
    usage = usage if usage is not None else Usage()
    tool_log: list[dict] = []
    started = time.time()

    if recorder:
        recorder.log(
            "instructions",
            system=system if isinstance(system, str) else "<blocks>",
            user_prompt=user_prompt if user_prompt is not None else messages[-1].get("content"),
            tools=[t["name"] for t in (tools or [])],
            json_schema=bool(json_schema),
        )

    stop_reason = "end_turn"
    for turn in range(max_turns):
        resp = client.create(system=system, messages=messages, tools=tools, json_schema=json_schema)
        usage.add_response(resp)
        stop_reason = resp.get("stop_reason", "end_turn")
        content = resp.get("content", [])

        for block in content:
            if block.get("type") == "thinking" and block.get("thinking"):
                if recorder:
                    recorder.log("thinking", turn=turn, summary=block["thinking"])

        if stop_reason == "refusal":
            if recorder:
                recorder.log("refusal", turn=turn, stop_details=resp.get("stop_details"))
            usage.latency_s += time.time() - started
            return ConversationResult("", usage, stop_reason, turn + 1, tool_log, True, messages)

        tool_uses = [b for b in content if b.get("type") == "tool_use"]

        if stop_reason == "pause_turn":
            # A server-side tool loop paused; resend to resume. No extra user turn.
            messages.append({"role": "assistant", "content": content})
            continue

        if not tool_uses:
            text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
            if recorder:
                recorder.log("final_message", turn=turn, stop_reason=stop_reason, text=text)
            usage.latency_s += time.time() - started
            messages.append({"role": "assistant", "content": content})
            return ConversationResult(text, usage, stop_reason, turn + 1, tool_log, False, messages)

        messages.append({"role": "assistant", "content": content})
        results = []
        for tu in tool_uses:
            name, args = tu.get("name", ""), tu.get("input", {}) or {}
            usage.tool_calls += 1
            if recorder:
                recorder.log("tool_call", turn=turn, tool=name, input=args)
            try:
                if dispatch is None:
                    raise LLMError(f"model called '{name}' but no dispatcher was supplied")
                out = dispatch(name, args)
                is_error = False
            except Exception as exc:  # surfaced to the model so it can recover
                out, is_error = f"Error: {exc}", True
            rendered = out if isinstance(out, str) else json.dumps(out, default=str)
            tool_log.append({"tool": name, "input": args, "output": out, "is_error": is_error})
            if recorder:
                recorder.log("tool_result", turn=turn, tool=name, output=out, is_error=is_error)
            block = {"type": "tool_result", "tool_use_id": tu["id"], "content": rendered}
            if is_error:
                block["is_error"] = True
            results.append(block)
        # All results for one assistant turn go back in a single user message.
        messages.append({"role": "user", "content": results})

    usage.latency_s += time.time() - started
    if recorder:
        recorder.log("exhausted", max_turns=max_turns)
    return ConversationResult("", usage, "max_turns", max_turns, tool_log, False, messages)


# --------------------------------------------------------------------------------------
# Verdict extraction
# --------------------------------------------------------------------------------------

def extract_json(text: str) -> dict | None:
    """Pull the verdict object out of a model reply.

    With output_config.format the whole reply is already JSON. Without it (v0), the model
    often wraps JSON in prose or a fence -- v0's format failures are a real measured
    result, so this stays tolerant but never guesses at missing fields.
    """
    if not text or not text.strip():
        return None
    s = text.strip()
    if s.startswith("```"):
        s = s.split("```")[1] if "```" in s[3:] else s[3:]
        if s.lstrip().lower().startswith("json"):
            s = s.lstrip()[4:]
        s = s.strip()
    try:
        parsed = json.loads(s)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    # Fall back to the outermost balanced {...} span.
    start = s.find("{")
    if start == -1:
        return None
    depth, in_str, esc = 0, False, False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(s[start:i + 1])
                    return parsed if isinstance(parsed, dict) else None
                except json.JSONDecodeError:
                    return None
    return None


def build_client(kind: str, model: str = DEFAULT_MODEL, effort: str = "high", **kw):
    if kind == "mock":
        return MockLLM(**{k: v for k, v in kw.items() if k == "responder"})
    if kind == "anthropic":
        return AnthropicClient(model=model, effort=effort)
    raise ValueError(f"unknown llm kind: {kind}")
