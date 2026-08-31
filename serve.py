"""ClearQueue console — a local web UI over the same code the CLI runs.

    python serve.py                      # replay mode, no credential needed
    python serve.py --port 9000
    python serve.py --no-browser

Why this exists
---------------
The CLI is the honest interface: it is what produced every number in CHANGELOG.md. But a
reviewer meeting this project for the first time should not have to read argparse output to
find out what an AP exception is. The console shows the queue the way the person doing the
job would see it -- an invoice, the evidence, a recommendation, and a signature line -- and
lets you open the trajectory behind any recommendation in one click.

Three data modes, and the difference between them matters
---------------------------------------------------------
**replay** (default) reads the committed trajectories in runs/recorded/. No API key, no
cost, no network, and the numbers on screen are the same ones score.py prints. This is what
a judge should use.

**live** re-runs one case against the real model right now. Costs roughly nine cents and
takes about half a minute. This is the mode that proves the trajectories were not hand-made.

**mock** runs the scripted fake model. It is labelled in the UI as what it actually is --
the always-approve control -- because that is its design: a mock run must score exactly what
`score.py --controls` reports for always_approve, and verify.py asserts that equality. It
demonstrates the harness, not the agent, and the UI says so rather than letting a viewer
mistake 41.7% for a result.

Nothing here pays anything. The approval gate writes a decision log and stops.

Standard library only -- no framework, no CDN, no fonts fetched at load. The console works
with the network cable pulled out, which is the same property the reproduction guide claims
for the scoring path.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import threading
import traceback
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse, parse_qs

import score as scorer
from clearqueue.config import LADDER, VERSIONS

ROOT = Path(__file__).resolve().parent
WEBAPP = ROOT / "webapp"
CASES = ROOT / "cases"
RECORDED = ROOT / "runs" / "recorded"
PACKETS = ROOT / "out" / "packets"
# Live and mock runs land under runs/_webapp/, which .gitignore already excludes via
# `runs/_*`. A demo must never be able to overwrite the committed evidence in runs/recorded/.
SCRATCH = ROOT / "runs" / "_webapp"
APPROVALS = ROOT / "out" / "approvals.jsonl"

DEFAULT_RUN = "final"

# Ground truth is not evidence. It is the answer key, it was never shown to any agent, and
# the UI only serves it from its own endpoint so it cannot leak into an evidence panel.
TRUTH_FILE = "expected.json"


# --------------------------------------------------------------------------------------
# Reading the committed artifacts
# --------------------------------------------------------------------------------------

def list_runs() -> list[str]:
    if not RECORDED.exists():
        return []
    names = [p.name for p in RECORDED.iterdir() if p.is_dir()]
    return sorted(names, key=scorer.ladder_order)


def load_invoice(case_id: str) -> dict:
    p = CASES / case_id / "invoice.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def evidence_files(case_id: str) -> list[str]:
    """Every file the agent could have opened, in the order it would list them."""
    base = CASES / case_id
    out = []
    for p in sorted(base.rglob("*")):
        if p.is_file() and p.name != TRUTH_FILE:
            out.append(p.relative_to(base).as_posix())
    return out


def read_trajectory(run: str, case_id: str) -> list[dict]:
    path = RECORDED / run / case_id / "trajectory.jsonl"
    return read_trajectory_path(path)


def read_trajectory_path(path: Path) -> list[dict]:
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                # A live run is being read while it is still being written; the last line
                # can be a partial write. Stop rather than reporting a corrupt trace.
                break
    return events


def trace_stats(events: list[dict]) -> dict:
    """The two facts a reviewer checks first: did it look, and did it have to be asked twice."""
    return {
        "tool_calls": sum(1 for e in events if e.get("type") == "tool_call"),
        "files_read": sorted({
            str(e.get("input", {}).get("path"))
            for e in events
            if e.get("type") == "tool_call" and e.get("tool") == "read_evidence"
            and e.get("input", {}).get("path")
        }),
        "citation_rejected": any(e.get("type") == "citation_rejected" for e in events),
        "verifier_ran": any(e.get("type") == "verifier_call" for e in events),
    }


# --------------------------------------------------------------------------------------
# Scoring, cached
# --------------------------------------------------------------------------------------

_truth_cache: dict[str, dict] | None = None
_score_cache: dict[str, dict] = {}


def truth() -> dict[str, dict]:
    global _truth_cache
    if _truth_cache is None:
        _truth_cache = scorer.load_truth(CASES)
    return _truth_cache


def score_recorded(run: str) -> dict:
    if run not in _score_cache:
        verdicts = scorer.load_verdicts(RECORDED / run)
        _score_cache[run] = scorer.score_run(truth(), verdicts, run)
    return _score_cache[run]


def score_control(strategy: str) -> dict:
    key = f"control/{strategy}"
    if key not in _score_cache:
        _score_cache[key] = scorer.score_run(
            truth(), scorer.control_verdicts(truth(), CASES, strategy), key)
    return _score_cache[key]


def summary_only(result: dict) -> dict:
    return {k: v for k, v in result.items() if k != "rows"}


# --------------------------------------------------------------------------------------
# Live and mock triage, run on a worker thread
# --------------------------------------------------------------------------------------

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
_job_seq = 0


def new_job(case_id: str, mode: str, version_name: str) -> str:
    global _job_seq
    trace = SCRATCH / version_name / case_id / "trajectory.jsonl"
    with _jobs_lock:
        _job_seq += 1
        job_id = f"job-{_job_seq}"
        _jobs[job_id] = {
            "id": job_id, "case_id": case_id, "mode": mode, "version": version_name,
            "status": "running", "verdict": None, "error": None,
            # Two forms on purpose. The API only ever emits the repo-relative one: an
            # absolute path would put a home directory in a JSON response, and this console
            # is meant to be screen-recorded.
            "trajectory": trace.relative_to(ROOT).as_posix(),
            "_path": trace,
        }
    return job_id


def compare_to_committed(case_id: str, version_name: str, verdict: dict) -> dict | None:
    """Did this run reproduce the committed trajectory for the same case?

    Deliberately *not* a comparison against ground truth. Ground truth is behind the
    "Reveal" button and stays there; a run that silently graded itself would take that
    choice away from whoever is looking. This answers a narrower and more useful question
    for someone who has just pressed a button on a screen already full of replayed data:
    is what I am now looking at the same answer that is committed to the repository, or a
    different one? Either result is informative. Disagreement is not a failure -- the model
    is not deterministic, and the citation column moved across five runs under identical
    levers, which is a documented finding rather than a bug.
    """
    committed_path = RECORDED / version_name / case_id / "verdict.json"
    if not committed_path.is_file():
        return None
    try:
        committed = json.loads(committed_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

    def amount(v: dict) -> float | None:
        try:
            return round(float(v.get("payable_amount")), 2)
        except (TypeError, ValueError):
            return None

    disp_same = verdict.get("disposition") == committed.get("disposition")
    amt_same = amount(verdict) is not None and amount(verdict) == amount(committed)
    return {
        "committed_disposition": committed.get("disposition"),
        "committed_amount": amount(committed),
        "live_disposition": verdict.get("disposition"),
        "live_amount": amount(verdict),
        "disposition_same": disp_same,
        "amount_same": amt_same,
        "identical": bool(disp_same and amt_same),
        "committed_path": (committed_path.relative_to(ROOT)).as_posix(),
    }


def run_job(job_id: str) -> None:
    """Execute one case. Identical call path to run.py -- no demo-only shortcut exists."""
    job = _jobs[job_id]
    case_id, mode, version_name = job["case_id"], job["mode"], job["version"]
    try:
        from clearqueue.arms import solve_case
        from clearqueue.llm import AnthropicClient, MockLLM
        from clearqueue.memory import VendorMemory
        from run import mock_responder

        version = VERSIONS[version_name]
        policy_text = (ROOT / "policy" / "ap_policy.md").read_text(encoding="utf-8")
        if mode == "mock":
            client = MockLLM(responder=mock_responder(CASES))
        else:
            client = AnthropicClient(model="claude-opus-5", effort="high", repo_root=ROOT)

        out_dir = SCRATCH / version_name / case_id
        memory = VendorMemory(SCRATCH / version_name / "memory" / "vendors.jsonl",
                              enabled=version.memory)
        verdict = solve_case(case_id, CASES / case_id, version, client, policy_text,
                             out_dir, memory=memory)

        # Rebuild the packet from the trajectory, exactly as run.py does, so the packet the
        # console shows after a live run is the same artifact the CLI would have written.
        from clearqueue import packet
        PACKETS.mkdir(parents=True, exist_ok=True)
        (SCRATCH / "packets").mkdir(parents=True, exist_ok=True)
        text = packet.render(case_id, CASES / case_id, verdict, out_dir)
        (SCRATCH / "packets" / f"{case_id}.md").write_text(text, encoding="utf-8")

        job["verdict"] = verdict
        # The packet the CLI would have written, returned so the console can replace the
        # committed one on screen. Showing a fresh verdict above a stale packet would be
        # worse than showing nothing.
        job["packet"] = text
        job["agreement"] = compare_to_committed(case_id, version_name, verdict)
        job["status"] = "done"
    except Exception as exc:                       # surfaced in the UI, not swallowed
        job["error"] = f"{type(exc).__name__}: {exc}"
        # A traceback is full of absolute paths. Strip the repo root before it reaches a
        # browser that may be on camera.
        job["traceback"] = traceback.format_exc()[-2000:].replace(str(ROOT) + "\\", "") \
                                                         .replace(str(ROOT) + "/", "")
        job["status"] = "error"


# --------------------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "ClearQueue"

    def log_message(self, fmt, *a):                # the console output stays readable
        pass

    # -- helpers ------------------------------------------------------------------
    def send_json(self, payload, status: int = 200) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, text: str, ctype: str = "text/plain; charset=utf-8") -> None:
        body = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def fail(self, status: int, message: str) -> None:
        self.send_json({"error": message}, status)

    def body_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    # -- routing ------------------------------------------------------------------
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = parse_qs(parsed.query)
        try:
            self.route_get(path, query)
        except BrokenPipeError:
            pass
        except Exception as exc:
            self.fail(500, f"{type(exc).__name__}: {exc}")

    def do_POST(self) -> None:
        path = unquote(urlparse(self.path).path)
        try:
            self.route_post(path)
        except BrokenPipeError:
            pass
        except Exception as exc:
            self.fail(500, f"{type(exc).__name__}: {exc}")

    def route_get(self, path: str, q: dict) -> None:
        if path == "/" or path == "/index.html":
            return self.send_text((WEBAPP / "index.html").read_text(encoding="utf-8"),
                                  "text/html; charset=utf-8")

        if path.startswith("/static/"):
            return self.serve_static(path[len("/static/"):])

        if path == "/api/bootstrap":
            return self.send_json(self.bootstrap())

        if path == "/api/ladder":
            controls = [summary_only(score_control(s)) for s in
                        ("always_approve", "always_hold", "always_escalate")]
            runs = [summary_only(score_recorded(r)) for r in list_runs()]
            return self.send_json({"controls": controls, "runs": runs})

        if path == "/api/queue":
            return self.send_json(self.queue(q.get("run", [DEFAULT_RUN])[0]))

        if path.startswith("/api/case/"):
            return self.send_json(self.case_detail(path[len("/api/case/"):],
                                                   q.get("run", [DEFAULT_RUN])[0]))

        if path.startswith("/api/evidence/"):
            return self.serve_evidence(path[len("/api/evidence/"):])

        if path.startswith("/api/truth/"):
            case_id = path[len("/api/truth/"):]
            return self.send_json(truth().get(case_id) or {})

        if path.startswith("/api/job/"):
            job = _jobs.get(path[len("/api/job/"):])
            if job is None:
                return self.fail(404, "no such job")
            events = read_trajectory_path(job["_path"])
            public = {k: v for k, v in job.items() if not k.startswith("_")}
            return self.send_json({**public, "events": events, "stats": trace_stats(events)})

        if path == "/api/approvals":
            return self.send_json({"decisions": self.read_approvals()})

        return self.fail(404, f"no route for {path}")

    def route_post(self, path: str) -> None:
        if path == "/api/triage":
            data = self.body_json()
            case_id = data.get("case_id", "")
            mode = data.get("mode", "mock")
            version_name = data.get("version", DEFAULT_RUN)
            if not (CASES / case_id / "invoice.json").exists():
                return self.fail(400, f"unknown case {case_id!r}")
            if version_name not in VERSIONS:
                return self.fail(400, f"unknown version {version_name!r}")
            if mode not in ("live", "mock"):
                return self.fail(400, "mode must be 'live' or 'mock'")
            job_id = new_job(case_id, mode, version_name)
            threading.Thread(target=run_job, args=(job_id,), daemon=True).start()
            return self.send_json({"job_id": job_id})

        if path == "/api/approve":
            return self.send_json(self.record_approval(self.body_json()))

        return self.fail(404, f"no route for {path}")

    # -- handlers -----------------------------------------------------------------
    def bootstrap(self) -> dict:
        from clearqueue.llm import resolve_credential
        try:
            cred = resolve_credential(ROOT)
            credential = {"available": True, "source": cred.source, "portable": cred.portable}
        except Exception as exc:
            credential = {"available": False, "source": str(exc), "portable": False}

        return {
            "runs": list_runs(),
            "default_run": DEFAULT_RUN if DEFAULT_RUN in list_runs() else (list_runs() or [""])[0],
            "credential": credential,
            "ladder": LADDER,
            "versions": [
                {"name": v.name, "headline": v.headline, "levers": v.levers(),
                 "hypothesis": v.hypothesis}
                for v in (VERSIONS[n] for n in [*LADDER, "vX-confidence", "final"])
            ],
            "case_count": len(truth()),
        }

    def queue(self, run: str) -> dict:
        if run not in list_runs():
            return {"error": f"unknown run {run!r}", "rows": []}
        result = score_recorded(run)
        verdicts = scorer.load_verdicts(RECORDED / run)
        rows = []
        for r in result["rows"]:
            cid = r["case_id"]
            v = verdicts.get(cid, {})
            inv = load_invoice(cid)
            meta = v.get("_meta", {})
            rows.append({
                **r,
                "vendor": inv.get("vendor_name_as_billed"),
                "invoice_number": inv.get("invoice_number"),
                "invoice_date": inv.get("invoice_date"),
                "po_number": inv.get("po_number"),
                "billed": inv.get("gross_amount"),
                "currency": inv.get("currency"),
                "payable_amount": v.get("payable_amount"),
                "required_approver_role": v.get("required_approver_role"),
                "defects": v.get("defects") or [],
                "citations": v.get("citations") or [],
                "rationale": v.get("rationale"),
                "tool_calls": meta.get("tool_calls", 0),
                "cost_usd": meta.get("cost_usd"),
                "latency_s": meta.get("latency_s"),
            })
        return {"run": run, "summary": summary_only(result), "rows": rows}

    def case_detail(self, case_id: str, run: str) -> dict:
        if case_id not in truth():
            return {"error": f"unknown case {case_id!r}"}
        verdicts = scorer.load_verdicts(RECORDED / run)
        verdict = verdicts.get(case_id, {})
        events = read_trajectory(run, case_id)
        pkt = PACKETS / f"{case_id}.md"
        return {
            "case_id": case_id,
            "run": run,
            "invoice": load_invoice(case_id),
            "evidence": evidence_files(case_id),
            "verdict": verdict,
            "score": scorer.score_case(truth()[case_id], verdict or None),
            "events": events,
            "stats": trace_stats(events),
            "packet": pkt.read_text(encoding="utf-8") if pkt.exists() else None,
        }

    def serve_evidence(self, rest: str) -> None:
        """Serve one evidence file. Confined to cases/, and the answer key is not in it."""
        case_id, _, relpath = rest.partition("/")
        if not case_id or not relpath:
            return self.fail(400, "expected /api/evidence/<case>/<path>")
        base = (CASES / case_id).resolve()
        target = (base / relpath).resolve()
        if base != target.parent and base not in target.parents:
            return self.fail(403, "path escapes the case directory")
        if target.name == TRUTH_FILE:
            return self.fail(403, "ground truth is served from /api/truth/, not as evidence")
        if not target.is_file():
            return self.fail(404, f"no such evidence file {relpath!r}")
        return self.send_text(target.read_text(encoding="utf-8"))

    def serve_static(self, name: str) -> None:
        target = (WEBAPP / name).resolve()
        if WEBAPP.resolve() not in target.parents or not target.is_file():
            return self.fail(404, "not found")
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_approvals(self) -> list[dict]:
        if not APPROVALS.exists():
            return []
        out = []
        for line in APPROVALS.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out

    def record_approval(self, data: dict) -> dict:
        """The gate. This is the only endpoint that writes a decision, and it writes a log."""
        reviewer = (data.get("reviewer") or "").strip()
        if not reviewer:
            return {"error": "a reviewer name is required; nothing was recorded"}
        decision = data.get("decision")
        if decision not in ("APPROVED", "REJECTED", "ESCALATED"):
            return {"error": "decision must be APPROVED, REJECTED or ESCALATED"}
        record = {
            "case_id": data.get("case_id"),
            "recommended": data.get("recommended"),
            "recommended_amount": data.get("recommended_amount"),
            "required_approver_role": data.get("required_approver_role"),
            "human_decision": decision,
            "note": (data.get("note") or "").strip() or None,
            "reviewer": reviewer,
            "decided_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "trajectory": f"runs/recorded/{data.get('run', DEFAULT_RUN)}/"
                          f"{data.get('case_id')}/trajectory.jsonl",
            "surface": "web console",
        }
        APPROVALS.parent.mkdir(parents=True, exist_ok=True)
        with APPROVALS.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        return {"recorded": record, "total": len(self.read_approvals())}


# --------------------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Serve the ClearQueue console.")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1",
                    help="loopback by default; this console has no authentication")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    missing = [p.name for p in (WEBAPP / "index.html", CASES, RECORDED) if not p.exists()]
    if missing:
        raise SystemExit(f"missing required paths: {', '.join(missing)}")

    url = f"http://{args.host}:{args.port}/"
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    runs = list_runs()
    print("ClearQueue console")
    print(f"  {url}")
    print(f"  {len(truth())} cases · {len(runs)} recorded runs · replay mode needs no credential")
    print(f"  recorded runs: {', '.join(runs)}")
    print("\nCtrl-C to stop.")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
