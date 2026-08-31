# Improvement changelog

Every entry is one lever, measured on all 24 cases before the next lever was added. The
versions are not forks: they are the same code path with different flags set in
`clearqueue/config.py`, so a delta is attributable to the lever rather than to a rewrite.

Reproduce any row:

```bash
python score.py --run runs/recorded/<version> --detail
python score.py --table runs/recorded/* --controls
```

Primary metric is **resolution accuracy** — disposition *and* payable amount correct to the
cent. Getting the disposition right with the wrong number does not count, because the wrong
number is what gets wired.

---

## The controls come first

Before any version is worth reading, here is what three strategies that involve no
reasoning at all score on this dataset:

| Strategy | Resolved | False approvals | Overpay exposure | Underpay exposure |
|---|---:|---:|---:|---:|
| always approve as billed | 41.7% | 100.0% | $56,922.28 | $32.50 |
| always hold | 16.7% | 0.0% | $0.00 | $112,462.26 |
| always escalate | 0.0% | 0.0% | $56,922.28 | $32.50 |

A result that does not beat all three is not a result. `always_approve` at 41.7% is the
number every version below has to clear before it has demonstrated anything, and it is the
reason the dataset was rebuilt — see the entry at the bottom of this file.

---

## v0-naive — the floor

**Lever:** none. One call, all evidence dumped into the prompt, no policy document, no
output schema. `evidence=dump`.

**Hypothesis:** a capable model with the documents in front of it gets most of this right
from general accounts-payable knowledge.

**Result:** it does not.

| | |
|---|---:|
| Resolution accuracy | **41.7%** (10/24) |
| Disposition accuracy | 45.8% |
| Approver accuracy | **29.2%** |
| Citation validity | 76.2% |
| Overpay exposure | $23,714.50 |
| Underpay exposure | $7,995.46 |
| Cost | $0.0230/case |

Exactly level with always-approve on the primary metric. The approver figure is the
cleanest signal in the table: 29.2% is roughly what guessing gets you, and it is guessing —
the clause 10 approval bands ($0–10k clerk, $10k–25k manager, above that controller) exist
only in the policy document, and v0 does not have the policy document.

The characteristic error is **treating every variance as a short-pay**. Cases 004, 016 and
018 all needed a HOLD; v0 short-paid all three, recommending $23,714.50 the policy does not
authorise. It is not being reckless, it is applying reasonable general practice — "pay what
you can justify, dispute the rest" — to a policy that says otherwise.

**Measurement caveat, stated because it affects how the next row reads.** Five of the 24
cases (005, 007, 012, 017, 020) returned no verdict at all: the API stopped with
`refusal`, `category: "cyber"`, on invoices for steel conduit, pallet rack beams and cable
glands. Reproducible across re-runs, and absent from every later version. The cause appears
to be the *shape* of v0's prompt — a bare wall of JSON with no framing — rather than the
data, which contains nothing bank-like (`cases/` has no account numbers, IBANs, routing
codes or credentials; grep it). Anthropic documents a fallback-model configuration for
exactly this. It was not added, because adding it mid-ladder would have changed the client
for some versions and not others.

So v0's floor conflates *the model got it wrong* with *the endpoint declined to answer*.
Excluding those five, v0 resolves **10 of 19 = 52.6%**. Every improvement claim below is
made against **v1-baseline**, not against v0, for this reason.

---

## v1-baseline — the policy document and a strict schema

**Lever:** `policy` + `schema`. Still one call, still all evidence dumped in, still no
tools. The full text of AP-POL-2026-03 goes in the system prompt and the response is
constrained to the verdict schema.

**Hypothesis:** fewer format failures, better tolerance calls.

**Result:** far larger than that.

| | v0 | v1 | Δ |
|---|---:|---:|---:|
| Resolution accuracy | 41.7% | **95.8%** | **+54.1pp** |
| Disposition accuracy | 45.8% | 95.8% | +50.0pp |
| Approver accuracy | 29.2% | **100.0%** | +70.8pp |
| Citation validity | 76.2% | 95.2% | +19.0pp |
| Overpay exposure | $23,714.50 | $4,300.00 | −$19,414.50 |
| Underpay exposure | $7,995.46 | $0.00 | −$7,995.46 |
| Cost | $0.0230 | $0.0229 | — |

Against the refusal-adjusted floor of 52.6% the gain is still +43pp, so it is not an
artifact of the refusals.

This is the single largest lever in the whole project and it cost nothing: same model, same
evidence, same number of API calls, same price per case. **Writing the policy down and
putting it in the prompt was worth more than every piece of agent machinery that follows.**

One case fails. **CASE-022** — Halcyon Facilities bills $4,300.00 against PO-4422 for
2026-02-15 to 2026-03-14, three weeks after billing $4,300.00 against the same PO for
2026-02-01 to 2026-02-28. Clause 8.1 rescues a repeat invoice when the service periods are
*distinct and non-overlapping*. These overlap by fourteen days. v1 noticed the tension and
escalated with a recommended payable of $4,300.00, which is a defensible thing for a human
to do and the wrong answer here: the clause 8 duplicate conditions are all met and 8.1 does
not apply. That single case is the entire $4,300.00 of remaining overpay exposure.

## v2-tools — deterministic calculators

**Lever:** `+ calc_tools`. Ten calculators — `uom_convert`, `apply_tolerance`,
`check_quantity`, `recompute_tax`, `fx_convert`, `net_credit_memos`, `approval_threshold`,
`compare_vendor_names`, `duplicate_check`, `line_total` — implemented in `Decimal` with
`ROUND_HALF_UP`. Evidence still dumped into the prompt.

**Hypothesis, stated before the run:** *"largest expected gain — arithmetic leaves the
model."*

**Result: the hypothesis is wrong, and this rung is a regression.**

| | v1 | v2 | Δ |
|---|---:|---:|---:|
| Resolution accuracy | 95.8% | 95.8% | **0.0** |
| Amount accuracy | 95.8% | 95.8% | 0.0 |
| **Citation validity** | 95.2% | **61.9%** | **−33.3pp** |
| **False approvals** | 0.0% | **8.3%** | **+8.3pp** |
| Overpay exposure | $4,300.00 | $4,300.00 | — |
| Cost | $0.0229/case | **$0.0668/case** | **×2.9** |
| Wall clock | 204s | 437s | ×2.1 |
| Tool calls | 0 | 118 | — |

Three times the cost, twice the latency, no accuracy gain, and two metrics worse.

**The arithmetic was never the bottleneck.** v1 was already correct to the cent on 23 of 24
cases doing the arithmetic in its head. There was no error for the calculators to remove.
The plan called this rung the largest expected gain; it is recorded here as a miss because
that is what the scorer says.

**The citation collapse is the interesting part.** v2 did not cite the *wrong* files — it
emitted an **empty** citations array on eight cases where v1 had cited correctly:

```
CASE-006   v1  ["invoice.json", "po.json", "receipt.json", "vendor.json"]
           v2  []
CASE-005   v1  [... , "correspondence/surcharge_approval.txt"]
           v2  []
```

Two things caused it. The model's notion of "the evidence I relied on" shifted from the
files to the tool results, which are not files and have no paths. And the prompt component
that says *cite the path of every file the decision rests on* is attached to the evidence
retrieval lever, which v2 does not have — v1 was citing well without ever being told to.
Adding a capability quietly removed a behaviour nobody had connected to it.

That is only visible because every metric is scored at every rung. A ladder that tracked
only the headline number would have recorded v2 as "no change, keep it" and shipped a
configuration that costs three times as much and cites nothing.

**And CASE-022 got worse.** v1 escalated the overlapping-period duplicate to a human. v2
approved it for $4,300.00 — the first false approval in the ladder. The calculators
confirmed that the line totals, the tax and the threshold all reconciled, which they do:
the invoice is arithmetically perfect. It is a duplicate. Giving the model a set of tools
that all answer *"the numbers are fine"* on the one case that is not about numbers appears
to have pulled it toward approval.

**Kept anyway,** for two reasons that are not accuracy: the tool log is what makes the
computation audit in each review packet checkable by a human, and clause 5's $0.02 rounding
allowance is the kind of thing that holds by luck until it does not. But it is kept knowing
it costs 2.9× and has never yet been the thing that fixed a case.

## v3-evidence — retrieval instead of a context dump

**Lever:** `evidence = "tools"`. The case documents leave the prompt. The agent gets
`list_evidence` and `read_evidence(path)` and is told to cite the case-relative path of
every file the decision rests on.

**Hypothesis:** fixes the cases where an email or a contract was in the prompt but ignored.

**Result: it fixes the damage v2 did, and nothing else.**

| | v1 | v2 | v3 |
|---|---:|---:|---:|
| Resolution accuracy | 95.8% | 95.8% | 95.8% |
| **Citation validity** | 95.2% | 61.9% | **100.0%** |
| False approvals | 0.0% | 8.3% | 8.3% |
| Overpay exposure | $4,300.00 | $4,300.00 | $4,300.00 |
| Cost | $0.0229 | $0.0668 | $0.0868/case |
| Tool calls | 0 | 118 | 234 |

Citation validity goes to **100.0%** — every case now cites the decisive file, including the
eight v2 had dropped and the one v1 missed. That is a clean confirmation of the v2
diagnosis: the citation collapse was caused by the calculators displacing the behaviour and
by the citation instruction living on this lever, and restoring the lever restores the
behaviour exactly.

It is worth being precise about what this rung did and did not buy. Retrieval did **not**
fix a single case that was previously decided wrongly. The hypothesis was that inlined
evidence gets skimmed and retrieved evidence gets read; on this dataset, v1 was already
reading the supplier emails and the contract clauses perfectly well from the prompt. What
retrieval bought is **provenance** — a reviewer can now see which files the decision rests
on, on every case, and that is the difference between a packet you can audit and a packet
you have to trust.

For a system whose entire output is a recommendation a human has to sign, that is worth the
cost. It is not an accuracy improvement and is not reported as one.

## v4-verifier — an independent control check

**Lever:** `+ verifier`. A second model call receives the proposed verdict, the tool log and
the evidence, and is asked to find the specific place where the number or the disposition
does not follow from the policy. If it objects, the agent gets one revision pass.

**Hypothesis:** drives the false-approval rate toward zero.

**Result: it did not catch the false approval, and it lost a case.**

| | v3 | v4 | Δ |
|---|---:|---:|---:|
| **Resolution accuracy** | 95.8% | **91.7%** | **−4.2pp** |
| Disposition accuracy | 95.8% | 95.8% | 0.0 |
| **Amount accuracy** | 95.8% | **91.7%** | −4.2pp |
| Citation validity | 100.0% | 90.5% | −9.5pp |
| False approvals | 8.3% | 8.3% | 0.0 |
| Overpay exposure | $4,300.00 | $4,300.00 | — |
| Underpay exposure | $0.00 | **$0.01** | +$0.01 |
| Cost | $0.0868 | **$0.1175/case** | ×1.35 |
| Wall clock | 572s | 774s | ×1.35 |

CASE-022, the case the verifier existed to catch, sailed through: the control check
confirmed a $4,300.00 approval of a duplicate. And on **CASE-020** the verifier changed a
correct answer into a wrong one.

### What actually happened on CASE-020

v3 answered **$1,793.75** and was right. The verifier objected — at length, coherently, and
citing the clause:

> *"Clause 5 (tax recompute) arithmetic: 206 × $8.10 = $1,668.60 net; 7.5% tax = $125.145,
> correct tax $125.14 and correct gross $1,793.74. The supplier billed $125.15, a $0.01
> overcharge. The $0.02 rounding allowance means this is not a defect, but it does not
> license paying the supplier's figure … Payable should be $1,793.74."*

The agent replied *"Correction accepted on both points"* and revised down a cent.

**The verifier is not obviously wrong.** Clause 5 opens with *"Recompute tax independently
… Do not trust the supplier's tax figure,"* and then says a gap under $0.02 is *"rounding,
not a defect"* — which states what to **flag** and never states what to **pay**. Read as
three parallel dispositions, the first bullet means accept the supplier's figure, which is
what the ground truth says. Read as a general instruction with an exception only to the
defect flag, the verifier is right.

**That is a hole in the policy document, and it is mine.** Two candidate cases were
rejected during dataset design for exactly this — no defensible single right answer — and
this one got through because the ambiguity is one clause away from where the case was
aimed. CASE-020 is the weakest ground truth in the set and is flagged as such.

The measured penny stands as an error, because the alternative is moving the target after
seeing the answer. **The policy was deliberately not amended**: v0 through v4 were measured
against this text, and editing it now would mean v5 and the shipping configuration were
scored against a different specification, which would make the whole ladder uncomparable.
The amendment clause 5 needs — *"where the supplier's tax is within the allowance, pay the
supplier's figure"* — belongs in the next revision of AP-POL-2026-03, which is a document
owned by the Controller's Office, not by this repository.

### The part that is not a caveat

Strip the ambiguity away and the finding holds: **the control check cost 35% more per case
and did not catch the one thing it was built to catch.** It confirmed the duplicate
approval on CASE-022 without objection. A verifier that re-derives arithmetic will find
arithmetic errors, and by v3 there were none left to find — every remaining failure is a
*judgment* failure about which policy clause governs, and asking the same model to re-check
its own judgment reliably produces agreement.

Worse, when it did produce disagreement, the agent folded on the one that mattered. Across
v4 and v5 the verifier ran 48 times and objected three times: twice on CASE-018, where the
agent read the objection, disagreed and kept its figure — which is exactly the behaviour the
revision prompt asks for (*"where it is wrong, say why in the rationale and keep your
figure"*) — and once on CASE-020, where it accepted a fluent objection and revised a correct
answer to a wrong one. **Three objections, zero real errors caught, one introduced.**

The failure mode of an LLM checking an LLM is not that it misses things. It is that when it
is confidently wrong it is persuasive, and the thing it is persuading already agrees with
everything it says.

**Cut.** The argument for keeping it was that the *packet* is better with it — a reviewer
who sees "the control check re-derived the figures and agreed" is in a different epistemic
position from one who sees the objections above, and the second is the point of a human
gate. That argument does not survive the measurement. A second opinion that is 0 for 3, that
costs 35% more per case, and whose one applied intervention was wrong is not evidence for a
reviewer; it is a confident-sounding line in a packet that means nothing. Shipping it
because it was work to build is precisely the failure this changelog exists to avoid.

It stays in the repo behind `--version v4-verifier`, with its measured record stated here.

## v5-memory — vendor facts carried across the queue

**Lever:** `+ memory`. A `recall_vendor` tool backed by `memory/vendors.jsonl`. After each
case the run writes back what it learned about that vendor — billing cadence, authorised
surcharges, name variants — and later cases in the queue can recall it. Memory is reset at
the start of every scored run and accumulates only from invoices already worked, never from
ones still ahead, which is the order a clerk would actually see them in.

**Hypothesis:** fixes the CASE-007 / CASE-008 discrimination — the duplicate under a vendor
name variant versus the legitimate monthly recurring charge.

**Result: the cent came back, the citations went away.**

| | v3 | v4 | v5 | v5 vs v3 |
|---|---:|---:|---:|---:|
| Resolution accuracy | 95.8% | 91.7% | **95.8%** | 0.0 |
| Disposition accuracy | 95.8% | 95.8% | 95.8% | 0.0 |
| Amount accuracy | 95.8% | 91.7% | 95.8% | 0.0 |
| **Citation validity** | 100.0% | 90.5% | **76.2%** | **−23.8pp** |
| False approvals | 8.3% | 8.3% | 8.3% | 0.0 |
| Overpay exposure | $4,300.00 | $4,300.00 | $4,300.00 | — |
| Cost | $0.0868 | $0.1175 | **$0.1407/case** | ×1.62 |
| Wall clock | 572s | 774s | 740s | — |
| Tool calls | 234 | 231 | 255 | — |

**The hypothesis was already dead before the lever was built.** CASE-007 and CASE-008 have
been correct since v1-baseline. The policy's clause 8.1 test — *are the service periods
distinct and non-overlapping* — is decidable from the two invoices alone, and the model was
deciding it correctly without any cross-case state. Memory was designed against a failure
that the written policy had already fixed two rungs earlier.

CASE-022 — the overlapping-period duplicate — was still approved. Memory did not help there
either, because the prior invoice is *in the case folder*: the agent has never lacked the
information, it has misread clause 8.1.

### The citation collapse — and a correction to how I first read it

Five cases (008, 012, 014, 023, 024) emitted an **empty** citations array where v3 had cited
correctly. It is worth being precise about what did and did not change:

```
                     read_evidence   list_evidence   citations on CASE-023
  v3-evidence            101              24         invoice, po, receipt, vendor,
                                                     correspondence/ceiling_authorisation.txt
  v5-memory              101              24         []
```

**Identical retrieval. The agent opened exactly the same 101 files.** It simply stopped
declaring which ones it relied on, on a subset of cases. `recall_vendor` was called exactly
once on every one of the 24 cases — including all the ones that kept their citations — so
recall did not displace the reads.

My first reading was that the memory lever broke citations, the same way the calculators
did in v2. **The next run falsified that.** `vX-confidence` runs v5's lever set *plus* one
more and scored 95.2% citation validity — one empty array, not five. Lining up the four
rungs that share the retrieval lever:

| Run | Levers | Cases with an empty `citations` array |
|---|---|---:|
| v3-evidence | policy, schema, calc, retrieval | **0** |
| v4-verifier | + verifier | 2 |
| v5-memory | + memory | 5 |
| vX-confidence | + confidence | 1 |

That is not a lever effect. **That is run-to-run variance in an unenforced instruction**,
and it is a worse finding than the one I thought I had. A lever that breaks citations can be
removed. An instruction that silently holds 100% of the time on Monday and 76% on Tuesday
cannot be fixed by removing anything — it has to be *enforced*, in the harness, by rejecting
a verdict that cites nothing and asking again. It is not enforced here, and that is the
clearest piece of unfinished work in this repo.

What survives from the v2 diagnosis is narrower but still true: v2's collapse to 61.9% was
caused by a missing prompt component and was fully repaired by restoring it, which is a
mechanism. The v5 number is noise on top of that mechanism, and reporting it as a second
instance of the same cause would have been a story fitted to one run.

The reason any of this is visible is that citation validity is scored on every rung. Nothing
errored. No amount moved. If this ladder tracked only resolution accuracy, the fragility
would still be there and nobody would know.

**Cut anyway.** 62% more expensive than v3, and not one case changed hands. The citation
figure is not the reason; it is not stable enough to be a reason.


## vX-confidence — the removal experiment

**Lever:** `+ confidence`. The verdict schema gains a required `confidence` field —
`high` / `medium` / `low` — and the harness skips the verification pass whenever the model
rates itself `high`. Built on top of v5, so this is v5 with a shortcut.

**Hypothesis, written down before the run:** *"Cheaper and probably no less accurate on
aggregate — and that is the trap. Self-rated confidence is expected to be highest exactly
where the model is confidently wrong, so false approvals should rise even if accuracy does
not fall."*

**Result: half right, and the wrong half is the interesting one.**

| | v5 | vX | Δ |
|---|---:|---:|---:|
| Resolution accuracy | 95.8% | 95.8% | 0.0 |
| Citation validity | 76.2% | 95.2% | (see v5, this is noise) |
| **False approvals** | 8.3% | **8.3%** | **0.0** |
| Overpay exposure | $4,300.00 | $4,300.00 | — |
| Cost | $0.1407 | **$0.0973/case** | **−31%** |
| Wall clock | 740s | 549s | −26% |

Cheaper, and false approvals did **not** rise. The prediction was wrong.

### Why it was wrong, which is worse than if it had been right

```
  self-rated confidence across 24 cases:   {'high': 24}
  verification skipped:                     24/24
  verification actually ran:                 0/24
```

**The model rated itself `high` on every single case.** Including CASE-022 — the
overlapping-period duplicate it approved for $4,300.00, the one case in the set it got
wrong. There is no case in this dataset on which it expressed a shred of doubt.

So false approvals did not rise because **the gate is not a gate.** It fires 24 times out of
24; it partitions nothing. A signal that takes one value on every input carries zero bits.
The experiment was designed to show that self-rated confidence is *miscalibrated*, and it
found something flatter: on this task it is not a measurement at all.

And that is why the cost fell 31% with nothing lost — because what got skipped was the
verification pass, and **v4 already established that the verification pass was worth
nothing.** Across the 48 verifier invocations in v4 and v5 it raised three objections: one
on CASE-018 that the agent correctly declined, twice; and one on CASE-020 that the agent
accepted and that made a correct answer wrong. Zero real errors caught, one introduced. A
shortcut that skips a worthless check saves money and loses nothing, which is exactly what
the numbers show.

**Removed, as planned — but not for the reason planned.** It is not removed because it is
dangerous; on this dataset it is measurably harmless. It is removed because it is a control
that cannot control anything, and shipping one is worse than shipping none: a reviewer
reading *"the model self-rated its confidence as high"* in a packet would reasonably take it
as information about that case. It is not. It is a constant.

The honest version of this lever is to delete the field and say so, which is what `final`
does.


## v6-enforce — the harness checks the citation instead of asking for it

**This rung was not planned.** It exists because the scorer caught something the ladder was
not built to look for, and the honest response to finding a defect in your own system on
deadline day is to fix it, not to describe it well.

**The defect.** Citation validity across five runs that all carried the identical instruction
*"cite the case-relative path of every file the decision rests on"*:

| Run | Levers | Resolution | Citation validity |
|---|---|---:|---:|
| v3-evidence | policy, schema, calc, retrieval | 95.8% | 100.0% |
| v4-verifier | + verifier | 91.7% | 90.5% |
| v5-memory | + verifier, memory | 95.8% | 76.2% |
| vX-confidence | + verifier, memory, confidence | 95.8% | 95.2% |
| v3-rerun-unenforced | **identical to v3** | 95.8% | **71.4%** |

The last row is the one that settles it. Same levers as v3, same code, same cases — 100.0%
and 71.4%. The instruction was never enforced. It was a sentence in a prompt, and whether it
was obeyed was a property of the run rather than of the system.

**Lever:** `+ enforce_citations`. After the verdict parses, the harness asks two questions of
it: is the `citations` array non-empty, and does every path in it actually exist in the case
folder? If either fails, the model is sent one message naming the problem and asked to return
**the same verdict** with the paths filled in. Exactly one retry — a loop that asks until it
likes the answer is a loop that manufactures the metric it is measuring. `expected.json` is
explicitly rejected as a citation; it is the answer key, and citing it would be a leak.

The check is deliberately weak. At run time the harness has no ground truth, so it cannot ask
*"did you cite the decisive file"* — only *"did you cite anything, and can I open it."* Those
two are enough to catch the observed failure and cannot be satisfied by inventing a plausible
filename.

**Hypothesis, written down before the run:** *"Citation validity should stop being a coin
flip. Resolution accuracy should not move at all — the re-ask only asks for provenance, never
for a different answer. If accuracy does move, the check is doing something it was not
supposed to do and must come out."*

### Result

The check fired on 2 of 24 cases and resolved both. To attribute the delta cleanly, the same
run was re-scored with the two re-asked cases rolled back to their pre-retry answers — model
behaviour held fixed, only the check removed. Comparing `final` against
`v3-rerun-unenforced` instead would fold in exactly the run-to-run variance this rung exists
to fix, which is the mistake the v5 entry above records. Rebuild it with
`python make_counterfactual.py`; it replays committed trajectories and touches no model.

| | check off | check on | Δ |
|---|---:|---:|---:|
| Resolution accuracy | 91.7% | **95.8%** | **+4.2** |
| Citation validity | 90.5% | **100.0%** | **+9.5** |
| **False approvals** | 2/12 = 16.7% | **1/12 = 8.3%** | **−8.4** |
| Overpay exposure | $4,300.00 | $4,300.00 | — |
| Cost | \$0.0873/case | \$0.0873/case | +2 calls, under a cent |

**And the hypothesis was wrong — in the direction that makes the lever more valuable, not
less.** Accuracy did move. By my own stated kill condition I should now cut this lever. I am
keeping it, and the reason is worth the space.

### Two different failures, one test

The two cases that were caught failed for opposite reasons, which is only visible in the
trajectories:

**CASE-018 — looked, but did not say.** Ten tool calls on the first pass, then an empty
`citations` array. The re-ask needed **zero** new tool calls: it simply filled in the five
paths it had already read. `verdict_moved: false`. The answer was correct before and after.
This is the failure I built the check for — a reporting lapse.

**CASE-007 — did not look at all.** Zero tool calls on the first pass. What came back was:

```json
{"case_id":"CASE-007","citations":[],"defects":[],
 "disposition":"APPROVE_FOR_PAYMENT","payable_amount":0.0,"rationale":""}
```

An empty rationale, no defects, no evidence read, and **`APPROVE_FOR_PAYMENT` on an invoice
whose ground truth is `DUPLICATE_REJECT`.** It parsed, so nothing errored; it would have been
scored as a wrong disposition and counted as a false approval — the money-losing error class.

The re-ask sent it back for paths. It made seven tool calls, read `vendor.json`, found prior
invoice NW-9912 already PAID against the same PO, and returned the correct verdict opening
with: *"I must correct my earlier verdict rather than merely re-cite it."*

**That is why the kill condition was wrong.** It assumed an empty `citations` array is a
formatting lapse. Sometimes it is an accurate report — the model cited nothing because it
consulted nothing. Asking for provenance is therefore not a cosmetic request: on a verdict
built on no evidence, the only way to answer it is to go and do the work. The check
accidentally tests something stronger than citation hygiene. It tests whether the answer has
a basis at all.

### What this lever does and does not buy

It is a **floor, not a lift.** Two of the three other runs of this lever set never produced a
zero-tool-call verdict, so on a well-behaved run the check costs two extra API calls and
changes nothing. It does not make the model better. What it does is remove a failure mode
from the set of things that can leave the building silently: after v6 there is no run of this
system that can recommend a payment citing nothing.

The +4.2 accuracy is honestly reported as *one case on one run*, worth exactly 4.2 points on
a 24-case set, and it is not claimed as a repeatable accuracy gain. The claim this rung is
entitled to make is the citation column and the false approval it demonstrably caught.

**Kept, and shipped in `final`.**


## final — what actually ships

Three of the seven levers built after the baseline were removed. The shipping configuration is
**v3's lever set plus the one lever that was added after measurement exposed a defect**:
policy document, strict output schema, deterministic calculators, evidence retrieval, and a
harness-enforced citation check. No verifier. No memory. No confidence field.

| Rung | Resolved | Citations | False appr. | Cost/case | Verdict |
|---|---:|---:|---:|---:|---|
| v0-naive | 41.7% | 76.2% | 0.0% | $0.0230 | the floor — level with always-approve |
| v1-baseline | 95.8% | 95.2% | 0.0% | $0.0229 | policy + schema — **kept** |
| v2-tools | 95.8% | 61.9% | 8.3% | $0.0668 | calculators — **kept**, for audit not accuracy |
| v3-evidence | 95.8% | 100.0% | 8.3% | $0.0868 | retrieval + citation — **kept** |
| v4-verifier | 91.7% | 90.5% | 8.3% | $0.1175 | control check — **cut**, 0 for 3 |
| v5-memory | 95.8% | 76.2% | 8.3% | $0.1407 | vendor memory — **cut**, no case changed |
| vX-confidence | 95.8% | 95.2% | 8.3% | $0.0973 | self-rated confidence — **cut**, 24/24 `high` |
| v3-rerun-unenforced | 95.8% | 71.4% | 8.3% | $0.0915 | v3's levers again — the run that exposed v6 |
| **final** (v3+v6) | **95.8%** | **100.0%** | **8.3%** | **$0.0873** | **ships** |

v3 dominates v4, v5 and vX on every metric *and* costs the least. Keeping the verifier, the
memory or the confidence field because they were more work to build would be the whole
failure mode this changelog exists to avoid. v6 is the only thing added on top, and it was
added because a measurement demanded it rather than because it was on the plan.

**What that leaves, stated plainly.** The shipping system is a single model call with a
written policy, a strict schema, a set of deterministic calculators, a retrieval tool and one
harness check on its output — and the honest summary of seven rungs of iteration is that the
things which moved the number were *writing the rules down*, *not letting the model do
arithmetic*, and *checking one property of the output instead of asking for it politely*. The
rest of the agent machinery earned its place on auditability or did not earn its place at all.

### What is still broken, and what I would do next

1. **CASE-022 is unsolved.** The overlapping-period duplicate is approved by every rung from
   v2 onward and is the entire $4,300.00 of remaining overpayment exposure. v1-baseline
   handled it *better*, by escalating. The tools all report "the arithmetic reconciles" on a
   case that is not about arithmetic, and that appears to pull the model toward approval.
2. **The citation check is weak on purpose, and the weakness is real.** It verifies that
   something was cited and that the path opens. It cannot verify that the *decisive* file was
   cited, because the harness has no ground truth at run time — only the scorer does. A
   verdict that cites `invoice.json` and nothing else passes the check and can still be
   unevidenced. Closing that needs a per-clause evidence requirement in the policy itself,
   which is a policy change rather than a harness change.
3. **Clause 5 needs one more sentence.** See the CASE-020 adjudication in the v4 entry.
4. **No variance estimate.** One run per rung, 24 cases, one model at one effort setting. A
   single case is worth 4.2 percentage points; the citation column demonstrated directly that
   run-to-run noise is large enough to invent a finding if you let it — and it did, once, and
   the correction is in the v5 entry.
5. **CASE-007 should not have been recoverable.** A verdict arrived with zero tool calls, an
   empty rationale and an approval on a duplicate. The citation check caught it by accident.
   A harness that means to catch that should check it directly: a verdict produced without a
   single evidence read is not a verdict, and the tool log already knows.



---

## Not a version: the dataset was rebuilt mid-project

Worth recording because it changed every number above.

The original dataset had 14 cases, one per failure mode. Scored on it, **v1-baseline
resolved 14 of 14 — 100% on every metric** — and a repeat run reproduced all fourteen
dispositions and amounts identically, so it was stable rather than lucky. That is a broken
experiment. With no headroom above the baseline, v2 through v5 could not have demonstrated
anything, and any flat line would have been unreadable: indistinguishable from a ceiling,
a bug in the harness, and a lever that genuinely does nothing.

The tempting fix is to weaken the baseline — take the policy away, use a smaller model,
constrain the prompt — and it is the wrong fix, because then the comparison is against a
straw man and the reported gain is manufactured.

The actual defect was in the dataset, and re-reading the policy made it obvious: **every
clause has two sides, and the 14 cases tested one side each.** There was a price variance
outside tolerance and a variance cured by authorisation, but no authorisation that *exists
and fails* the clause 3.1 conditions. There was a tax overcharge but no undercharge, where
the policy requires paying *more* than billed. There was over-delivery beyond the 5% band
but none inside it. There was a duplicate and a legitimate recurring charge, but no
overlapping-period case. Nothing in the set produced a payable between $10,000.01 and
$25,000, so the entire `AP_MANAGER` approval band was untested. And the $50.00 per-line cap
in clause 3 — which binds *below* the 2% band on expensive items and is the clause's whole
point — was never the binding constraint in any case.

Ten cases (015–024) were added, each pinned to a named clause branch. `always_approve` fell
from 57.1% to 41.7%, which is the honest measure of how much the original dataset was
giving away for free. Two candidate cases were considered and rejected as having no
defensible single right answer: an FX invoice with no contract rate (clause 7 escalates,
but the recommended payable is genuinely undefined) and a missing goods receipt on a GOODS
purchase order (HOLD_QUANTITY_VARIANCE and ESCALATE_HUMAN are both readable from the
policy). Ground truth you have to argue about is not ground truth.

The 14-case ladder run in progress at the time was killed rather than finished. It would
have cost about forty minutes and produced a flat line measuring nothing.
