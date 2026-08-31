# Reproducing ClearQueue

Every headline number in `README.md` is reproducible on a clean machine **without an API
key and without network access.** That is a design constraint rather than a convenience:
hackathon ground rule 08 keeps credentials out of the submission, so nobody evaluating
this will hold a credential capable of running it. A reproduction path that needs one is a
reproduction path that does not work.

---

## Requirements

| | |
|---|---|
| Python | 3.11 or newer (developed on 3.14.7) |
| Packages to install | **none** |
| Network | not needed for any verification step |
| Disk | ~15 MB |

There is no `requirements.txt` because there are no dependencies. The Anthropic API is
reached over the standard library's `urllib.request`. If `python --version` prints 3.11 or
above, you have everything.

---

## The one command

```bash
python verify.py
```

Expected output:

```
ClearQueue offline verification — no API key, no network.

  PASS  tools selftest   Tools selftest passed (29 checks).
  PASS  scorer selftest   Scorer selftest passed (5 checks).
  PASS  mock triage (24 cases)   24/24 verdicts written
  PASS  mock == always-approve control   mock == always_approve on all 6 metrics (resolution 41.7%)
  PASS  replay committed traces   resolution 95.8%  false-approval 8.3%

  All 5 stages passed. The measured results in README.md are
  reproducible on this machine without a credential.
```

Takes about 90 seconds, almost all of it stage 3.

Any stage can fail independently. What each one establishes:

1. **tools selftest** — the deterministic calculators (UOM conversion, the price tolerance
   band, tax, FX, credit netting, approval thresholds) agree with hand-worked arithmetic.
2. **scorer selftest** — the metric is not rigged. Known-good, off-by-one-cent, missing and
   degenerate verdicts are pushed through the scorer and must produce the accuracy figures
   they should. A scorer that always returns a flattering number fails here.
3. **mock triage** — the whole pipeline runs end to end on all 24 cases against a scripted
   fake model. No credential, no cost, no network.
4. **mock == always-approve** — the invariant worth reading twice. The mock's scripted
   policy *is* the always-approve control strategy, so scoring the mock run must equal
   scoring that control on every metric. If the harness were quietly adding signal the
   model did not produce, these two numbers would separate. Note that the mock is run under
   the `final` configuration, citation check and all: the check fires on every mock case,
   fails to obtain a citation, and the invariant still holds — which is the point. A retry
   that could manufacture the metric it is checking would break this stage.
5. **replay committed traces** — re-scores the trajectories in `runs/recorded/` and
   reproduces the exact table in the README.

---

## The console, if you would rather click than type

```bash
python serve.py
```

Opens `http://127.0.0.1:8765` in your browser. No credential, no installs, no network — it
reads the committed trajectories in `runs/recorded/` and serves them with the standard
library's `http.server`. There are no CDN links, no web fonts and no external requests in
the page, so it renders with the network cable pulled.

Four screens:

- **Exception queue** — all 24 invoices with the recommendation, the amount, the approver,
  the evidence cited, and whether it matched ground truth. The summary cards are the same
  numbers `score.py --run runs/recorded/final` prints.
- **Case detail** — the evidence files as the agent could read them, the recommendation, the
  review packet, and the full trajectory as a timeline you can expand event by event.
  `CASE-007` is the one to open: the citation check fires, and the second pass changes the
  answer.
- **How it was built** — the three degenerate controls, then the ladder, then each version's
  written hypothesis *from before it was run*.
- **Approval log** — the gate. Sign a case and it appends to `out/approvals.jsonl`.

Two things the console can do that replay cannot, both on the Case detail screen:

| Mode | What it does | Cost |
|---|---|---|
| **live** | re-runs one case against the real model right now, streaming the trajectory as it happens | ~$0.09, ~30 s, needs `.env.local` |
| **mock** | runs the scripted fake model | free |

**Read the mock honestly.** The mock's scripted policy *is* the always-approve control — that
equality is stage 4 of `verify.py`. It approves every invoice at the billed amount and cites
nothing, so a mock-driven demo shows 41.7% and every duplicate paid. It demonstrates that the
harness works; it does not demonstrate the agent, and the console says so on screen rather
than letting the number be mistaken for a result.

The console's "run it now" button calls the same `solve_case()` that `run.py` calls. Its
output goes to `runs/_webapp/`, which is gitignored — a demo cannot overwrite the committed
evidence in `runs/recorded/`.



```bash
# the headline comparison, plus the three degenerate controls
python score.py --table runs/recorded/* --controls

# one version in detail, case by case
python score.py --run runs/recorded/final --detail

# baseline against the shipping configuration
python score.py --compare runs/recorded/v1-baseline runs/recorded/final
```

The controls matter for reading the table honestly. `always_approve`, `always_hold` and
`always_escalate` are strategies that involve no reasoning at all; they show how much of
any score comes free from the shape of the dataset rather than from the agent. A result
that does not beat all three is not a result.

Two directories in the bundle are not ladder rungs and are named so:

- **`v3-rerun-unenforced`** — v3's *identical* lever set, run a second time. It scores the
  same resolution accuracy and 71.4% citation validity against v3's 100.0%. This is the
  measurement that produced the v6 lever.
- **`v6-counterfactual-no-check`** — `final` with the two re-asked cases rolled back to their
  pre-retry answers, so model behaviour is held fixed and only the citation check is removed.
  Rebuild it from the committed trajectories with `python make_counterfactual.py` (no model,
  no network — it only replays what was recorded). It is the evidence behind the v6 delta
  claimed in `CHANGELOG.md`:

  ```bash
  python score.py --table runs/recorded/final runs/recorded/v6-counterfactual-no-check
  ```
  ```
  final                       95.8  95.8  95.8   8.3  ...  100.0
  v6-counterfactual-no-check  91.7  91.7  95.8  16.7  ...   90.5
  ```

---

## Rebuilding the dataset from source

```bash
python build_dataset.py
```

Regenerates all 24 cases under `cases/`. Ground-truth figures in `build_dataset.py` are
hand-derived literals, deliberately **not** computed by the script — a bug in the harness
therefore cannot quietly move the target. The script's assertions check only *internal
consistency* of the generated documents (line amounts sum to the net, net + tax = gross as
billed, dispositions agree with the approval threshold and the escalation rule), which
catches typos without re-deriving the answer.

`cases/CASE-XXX/expected.json` is the ground truth. It is never shown to any agent: the
evidence loader explicitly refuses to read it, and the refusal is one of the 29 tool
selftest checks.

---

## Running it live (optional, needs your own key)

Only required if you want to generate *new* trajectories. The committed ones already
support every claim.

```bash
cp .env.example .env.local        # Windows: Copy-Item .env.example .env.local
# put your key in .env.local — it is gitignored and must never be committed

python run.py --probe                                  # check the endpoint supports what is needed
python run.py --version final --llm anthropic          # one scored run
python run.py --ladder  --llm anthropic                # every version, in order
python score.py --table runs/* --controls
```

`--probe` is worth running first. It exercises the five API features the ladder depends on
(plain messages, tool use, structured output, prompt caching, tools and schema together)
for a few hundred tokens, so an endpoint that accepts simple calls but rejects structured
output fails in seconds rather than an hour in.

A key placed in `.env.local` is only ever sent to `api.anthropic.com` unless that same file
names a different endpoint on purpose. See `resolve_credential()` in `clearqueue/llm.py`.

---

## The human approval gate

```bash
python run.py --review --out runs/recorded/final
```

Steps a reviewer through the queue one case at a time, showing the recommendation, the
amount, the defects, the evidence cited and the rationale, and records the decision to
`approvals.jsonl`. Needs a real terminal for input.

Nothing in this project pays anything. `payable_amount` is the amount released **if** the
approver named in policy clause 10 signs off. That is the whole point of ground rules 04
and 05, and it is enforced structurally: there is no payment code path to disable.

---

## Directory map

```
policy/ap_policy.md      the AP policy — the shared context both arms receive
cases/CASE-001..024/     the dataset; expected.json is ground truth, never shown
build_dataset.py         regenerates cases/ with consistency assertions
clearqueue/
  llm.py                 stdlib urllib client, mock, trace recorder, credential resolution
  tools.py               deterministic calculators — they compute, they never decide
  config.py              the version ladder as configuration, not forked code
  prompts.py             system/user prompts and the strict verdict schema
  arms.py                the single solve path all versions share, including the
                         citation check the harness enforces — the v6 lever, kept
  verifier prompts       in prompts.py — the v4 lever, measured and cut from `final`
  memory.py              cross-invoice vendor memory — the v5 lever, measured and cut
  packet.py              renders the human review packet from the trajectory
  probe.py               endpoint feature probe
run.py                   triage CLI and the review gate
score.py                 deterministic scorer, controls, selftest, replay
verify.py                the five-stage offline check above
serve.py                 the local console — routes, replay/live/mock, the approval endpoint
webapp/                  index.html, app.js, style.css — no framework, no CDN, no web fonts
runs/<version>/<case>/   trajectory.jsonl + verdict.json for every case
runs/recorded/           the frozen bundle the README numbers come from
runs/_webapp/            scratch output from the console's live and mock runs (gitignored)
out/packets/CASE-XXX.md  human review packets
```

---

## Notes and known limitations

- **The dataset is synthetic** (ground rule 07). Vendor names, buyers and email addresses
  are invented and all domains use `.example`. No real supplier data appears anywhere.
- **24 cases is a small sample.** A single case is worth 4.2 percentage points, so
  differences smaller than that should not be read as signal. The per-case detail view
  (`--detail`) is more informative than the headline for small deltas.
- **Trajectories are recorded from a session proxy endpoint**, not `api.anthropic.com`.
  This affects nothing about the scores — the traces and the scoring are identical either
  way — but it is why the reproduction path is replay-based rather than re-execution.
- **The scorer is deterministic and contains no model.** Disposition and amount are
  compared to hand-authored ground truth; the amount must match to the cent.
