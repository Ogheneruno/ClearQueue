# ClearQueue

**An accounts-payable exception triage agent.** It reads the invoice, the purchase order,
the goods receipt, the contract and the supplier's email; applies a written AP policy; and
hands a human a signable recommendation with the arithmetic shown. It never pays anything.

```bash
python verify.py        # no API key, no network, no installs
```

---

## 1. Thursday, 4:40pm

Amara works accounts payable at a company that buys steel conduit, cable glands and pallet
rack. About two hundred supplier invoices arrive a week. The ERP matches roughly seventy
percent of them automatically against the purchase order and the goods receipt, and those
are paid without anyone looking at them.

The other sixty land in the exceptions queue, and the exceptions queue is Amara.

She opens the next one. Kestrel Industrial has billed for **480 EACH at $2.00**. The
purchase order says **40 CASE at $24.00**. Those are the same goods — a case is twelve —
and the two figures reconcile exactly, but no rule in the ERP knows that, because the pack
size lives in a vendor master field that the matching engine does not read. Two minutes.

Next one. Kestrel again, six percent over the PO price. The ERP flagged it and it is right
to: six percent is outside the two percent tolerance. But three screens away, in a mail
folder, there is an email from the supplier announcing an alloy surcharge, countersigned by
Dele Fashanu, who is a buyer authorised for this vendor, referencing this purchase order,
approving up to six percent. The variance is cured. Paying it is correct. Holding it is a
mistake that costs the early-payment discount and starts a phone call. Eleven minutes,
most of it spent finding the email.

Next one. Halcyon Facilities, $5,160.00, and there is another Halcyon invoice for exactly
$5,160.00 from three weeks ago. Duplicate? The amounts match, the PO matches, the vendor
matches. It is not a duplicate: one covers February and one covers March. It is a monthly
service contract. Rejecting it would be, in the words of the policy she is supposed to be
applying, *"a supplier-relationship failure, and is treated as seriously as an
overpayment."*

Then the same-looking case where the service periods **overlap**, which *is* a duplicate.

It is 4:40pm and there are thirty-one invoices left.

### What is actually hard here

Every invoice in that queue is there **because the rules already failed on it.** That is
the definition of an exception. So the tempting fix — write better rules — is the one fix
that provably does not work; it is what produced the queue.

The deciding fact is almost never in the structured data. It is in a unit of measure that
needs a vendor master lookup, or a sentence in an email, or a clause in a contract, or the
absence of a goods receipt on a services PO where absence is correct and must not be raised
as an exception at all.

And both directions of error cost money. Approve a duplicate and you have wired funds you
will spend a quarter clawing back. Hold a legitimate invoice and you forfeit the 2/10
net 30 discount and damage a supplier. A system that resolves every doubt by holding is not
cautious, it is just a different kind of wrong — and it is the failure mode that naive
automation lands in every time.

That is the shape of a job for an agent: unstructured evidence, a written policy, real
judgment, and a verifiable right answer.

---

## 2. Why this problem and not a coding problem

Because it has **ground truth to the cent**.

A large share of agent demos are graded by another language model, or by a human reading
output and nodding. Both are unfalsifiable. Here, every case has a hand-authored correct
disposition and a correct payable amount, and `score.py` is ordinary Python with no model
in it. If the agent says `$6,639.20` and the truth is `$6,639.21`, it is wrong, and nothing
about how convincing its explanation was can change that.

That also means an *improvement* claim is checkable. Every number in section 3 comes from
re-scoring committed trajectories, offline, in about a second.

---

## 3. What was measured

24 hand-authored cases. A case counts as **resolved** only when the disposition *and* the
payable amount to the cent are both right. Every figure below comes from re-scoring committed
trajectories offline — `python score.py --table runs/recorded/* --controls`.

**Read the controls first.**

| Strategy | Resolved | Disposition | Amount | False approvals | Overpaid | Underpaid |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| always approve | 41.7% | 50.0% | 41.7% | 100.0% | $56,922.28 | $32.50 |
| always hold | 16.7% | 16.7% | 33.3% | 0.0% | $0.00 | $112,462.26 |
| always escalate | 0.0% | 8.3% | 41.7% | 0.0% | $56,922.28 | $32.50 |

These involve no reasoning at all. **Always-approve scores 41.7%** — that is how much of any
score comes free from the shape of the dataset, and it is the number a result has to beat
before it has demonstrated anything. Always-hold has a perfect false-approval rate while
withholding $112,462.26 from suppliers who should have been paid, which is why "false
approvals" is never reported on its own here.

**The ladder.** Same code path throughout; each row adds the lever named in it.

| Version | Lever added | Resolved | Citations | False appr. | $/case | Verdict |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| v0-naive | — | 41.7% | 76.2% | 0.0% | $0.0230 | level with always-approve |
| **v1-baseline** | **written policy + strict schema** | **95.8%** | 95.2% | 0.0% | $0.0229 | kept |
| v2-tools | deterministic calculators | 95.8% | 61.9% | 8.3% | $0.0668 | kept — for audit, not accuracy |
| v3-evidence | retrieval + citation | 95.8% | 100.0% | 8.3% | $0.0868 | kept |
| v4-verifier | independent control check | 91.7% | 90.5% | 8.3% | $0.1175 | **cut** — 0 for 3 |
| v5-memory | vendor memory | 95.8% | 76.2% | 8.3% | $0.1407 | **cut** — changed no case |
| vX-confidence | self-rated confidence | 95.8% | 95.2% | 8.3% | $0.0973 | **cut** — rated itself `high` 24/24 |
| v3-rerun | *(v3's levers, re-run)* | 95.8% | **71.4%** | 8.3% | $0.0915 | the run that exposed v6 |
| **final** | **+ enforced citations** | **95.8%** | **100.0%** | 8.3% | $0.0873 | **ships** |

**+54.1 points came from one change:** putting the written policy and a strict schema in
front of the same model, at the same cost, in the same number of API calls. Everything after
it — five more levers, up to 6× the cost per case — moved the resolution number by **zero**,
and three of those levers were cut after measurement for making things worse or nothing.

Two levers survived without moving accuracy, and the reason is the point: **the calculators
and the retrieval bought auditability.** A reviewer can check every figure against a
deterministic tool call and every claim against a cited file. For a system whose entire
output is a recommendation a person has to sign, that is the product — it just is not what
the accuracy column measures.

The last two rows are the honest part. `v3-rerun` is v3's *identical* lever set run a second
time: same code, same cases, 100.0% citations → **71.4%**. The instruction to cite was never
enforced, so whether packets carried provenance was a property of the run. `final` adds a
harness check — reject a verdict citing nothing or citing a file that does not exist, ask
once more. Holding model behaviour fixed and removing only that check, the same run scores
91.7% / 90.5% / **16.7% false approvals** instead of 95.8% / 100.0% / 8.3%. The full
adjudication, including the one case where asking for a citation caused the model to discover
it had approved a duplicate without reading anything, is the `v6-enforce` entry in
`CHANGELOG.md`.

**CASE-022 is the entire remaining exposure** — $4,300.00, an overlapping-period duplicate
that every rung from v2 onward approves. See §6.

---

## 4. How it works

One invoice, one pass:

```
     evidence                    policy AP-POL-2026-03
   po · receipt · invoice              (13 clauses)
   vendor · contract · email                │
          │                                 │
          └────────────┬────────────────────┘
                       ▼
            ┌──────────────────────┐
            │  triage agent        │  reads evidence through a retrieval tool,
            │                      │  cites the path of what it relied on
            └──────────┬───────────┘
                       │ every monetary computation
                       ▼
            ┌──────────────────────┐
            │ deterministic tools  │  uom_convert · apply_tolerance · check_quantity
            │ they compute,        │  recompute_tax · fx_convert · net_credit_memos
            │ they never decide    │  approval_threshold · duplicate_check · line_total
            └──────────┬───────────┘
                       ▼
            ┌──────────────────────┐
            │ citation check       │  cites nothing, or cites a file that does not
            │ (harness, not prompt)│  exist? → one re-ask, then it stands as it is
            └──────────┬───────────┘
                       ▼
              review packet  ──►  a named human signs, or does not

   built, measured, and cut:
     · an independent control check that re-derives the payable   (v4 — cost 35% more,
       from the tool log and can object                             lost a case, caught
                                                                    nothing)
     · vendor memory carried across the queue                     (v5 — cost 62% more,
                                                                    changed no case,
                                                                    broke citations)
     · model self-rated confidence gating the control check       (vX — rated itself
                                                                    `high` on 24 of 24)
```

The division of labour is the design. **The model decides; it does not calculate.** Which
tool to call, on what inputs, and what the results mean together is judgment, and that is
the model's job. Half-up cent rounding, the lower of 2% and $50.00, the 5% over-delivery
band, netting credit memos before reading the approval threshold — those are mechanical,
and a language model doing them by hand is a language model producing an answer that is
right most of the time. `tools.py` implements them in `Decimal` with `ROUND_HALF_UP`,
because Python's built-in `round()` is banker's rounding and would quietly cost half a cent
on ties.

Every version in the ladder is **the same code path with different levers** — see
`clearqueue/config.py`. There is no `if version == "v3"` anywhere in the solve path. That
is what makes a measured delta attributable to the lever rather than to a fork.

---

## 5. Nothing gets paid

Ground rules 04 and 05, enforced structurally rather than by policy: **there is no payment
code path to disable.** `payable_amount` is the amount released *if* the approver named by
clause 10 signs off.

Every case terminates in a review packet (`out/packets/CASE-XXX.md`) carrying the
recommendation, the defects, the evidence cited, the full computation audit and a signature
block. `python run.py --review` steps a named reviewer through the queue and appends each
decision — reviewer, UTC timestamp, recommendation, human decision, trajectory path — to
`approvals.jsonl`.

The packet is rebuilt **from the recorded trajectory**, not from the agent's summary of
itself. That direction of dependency is deliberate: a reviewer who does not trust the
rationale can read what was actually computed and what was actually opened, and if a
trajectory were ever too thin to reconstruct the decision, the packet would visibly
degrade rather than the gap going unnoticed.

Clause 13 of the policy says it plainly, and so does every packet footer: *ClearQueue
recommends; a person decides.*

**The same gate, with a screen.** `python serve.py` opens a local console at
`http://127.0.0.1:8765` showing the queue as the person doing the job would see it: the
invoice, the evidence files, the recommendation, the trajectory behind it, and a signature
block. It is a view over the same code — the console's "run it now" button calls the same
`solve_case()` that `run.py` calls, and there is no demo-only shortcut in it. Decisions
signed in the console append to `out/approvals.jsonl` in the same shape the CLI writes:

```json
{"case_id": "CASE-005", "recommended": "APPROVE_FOR_PAYMENT", "recommended_amount": 6016.56,
 "required_approver_role": "AP_MANAGER", "human_decision": "APPROVED",
 "note": "Surcharge email is countersigned by the buyer.", "reviewer": "A. Okafor, AP Manager",
 "decided_at": "2026-08-31T04:38:00+00:00",
 "trajectory": "runs/recorded/final/CASE-005/trajectory.jsonl", "surface": "web console"}
```

A reviewer name is required and an unknown decision is rejected; the endpoint that writes
the log is the only endpoint that writes anything. The console defaults to **replay** — it
reads the committed trajectories, needs no credential, makes no network calls, and shows the
same numbers `score.py` prints.

**Hosted, if you would rather not clone:** <https://ogheneruno.github.io/ClearQueue/> is that
replay half, pre-rendered by `build_static.py` and published from the `gh-pages` branch. Every
case, evidence file, trajectory, packet and score is the committed data, and ground truth is
still behind the Reveal button. Two things are missing there and say so on screen: "run it now"
needs a credential, which is never published, and signing an approval needs somewhere to write.
For those, clone and run `python serve.py`.

---

## 6. Honest notes

**CASE-022 was never solved.** An overlapping-period repeat invoice from Halcyon
Facilities, $4,300.00. Every rung from v2 onward approves it, including the shipping
configuration. It is the entire remaining overpayment exposure. The uncomfortable part:
**v1-baseline — the plain one-shot prompt — handled it better**, escalating it to a human
instead of approving it. Something about giving the model a toolbelt that keeps answering
*"the arithmetic reconciles"* on a case that is not about arithmetic pulls it toward
approval. The gate catches it, because a human sees a duplicate-shaped invoice with a
signature block under it. The agent does not.

**CASE-020's ground truth is contestable.** Clause 5 says a supplier tax figure within
$0.02 of the recomputed one is *"rounding, not a defect"* — and never says which of the two
figures to pay. v4's control check read it the other way, argued its case with the clause
number, and talked a correct answer down by a cent. The ground truth stands, but the clause
needs one more sentence, and the changelog says so. It is the weakest case in the set.

**v0's floor is contaminated.** Five of the 24 cases returned an API `refusal` under v0's
bare-JSON-wall prompt, on invoices for steel conduit and cable glands. Reproducible, absent
from every later version, and the dataset contains nothing bank-like. Excluding them, v0
resolves 52.6% rather than 41.7%. Every improvement claim in this repo is stated against
**v1-baseline**, not against v0, for that reason.

**One model, one effort setting, one run per rung.** `claude-opus-5` at `effort=high`. The
shipping configuration is a re-run of v3's lever set, which gives exactly one repeat
measurement and no variance estimate. A single case is worth 4.2pp, so ±1-case differences
are reported as "unchanged" rather than as small wins. The citation column demonstrated
this directly: under near-identical levers it read 100.0%, 90.5%, 76.2% and 95.2% on four
consecutive runs, which is large enough to manufacture a finding if you only run once. One
was manufactured, and then corrected — see the v5 entry in `CHANGELOG.md`.

**Citations were unenforced, and that was the real defect.** The agent was *told* to cite the
path of every file the decision rests on, and for six rungs nothing checked that it did. Under
near-identical levers the citation column read 100.0%, 90.5%, 76.2%, 95.2% and 71.4% across
five runs. The harness now rejects a verdict that cites nothing or cites a file that does not
exist and asks once more, which is what `final` ships. **The check is still weak on purpose:**
it verifies that something was cited and that the path opens, not that the *decisive* file was
cited — the harness has no ground truth at run time, only the scorer does. A verdict citing
`invoice.json` and nothing else passes it and can still be unevidenced.

**The dataset is synthetic and it is mine.** 24 cases, hand-authored with the ground truth
derived by hand from the policy, per ground rule 07. It was deliberately rebuilt once when
the first version turned out to be too easy (see the last entry in `CHANGELOG.md`), and it
is designed so every policy clause is tested on both of its sides. It is not a sample of any
real accounts-payable queue, and the accuracy numbers do not transfer to one.

**The 11-minute manual baseline is an industry figure, not a measurement.** The "human
minutes saved" line in `score.py` uses 11 minutes per exception manually and 2.5 minutes to
review a prepared packet. Neither was measured here. Treat that row as an illustration and
the accuracy rows as the result.

---

## 7. Hot take

**Most of what gets called agent engineering is compensating for a specification that was
never written down.**

The single largest improvement in this project was not the tools, the retrieval, the
verifier or the memory. It was **writing the policy down and putting it in the prompt**:
+54.1 points, for zero additional cost, zero additional API calls and zero additional
latency. Every piece of agent machinery built afterwards — six more rungs, five more levers,
up to 6× the cost per case — moved the headline accuracy number by **zero**, and three of
those levers were cut after measurement for making things worse or nothing at all.

That is not an argument that scaffolding is useless. The calculators and the retrieval both
survived, and they survived for a reason worth naming: **they bought auditability, not
accuracy.** A reviewer can check every figure against a deterministic tool call and every
claim against a cited file. For a system whose entire output is a recommendation a person
has to sign, that is the product. It just is not what the accuracy column measures, and
pretending otherwise would have been the easy version of this writeup.

The corollary is the more useful half. If your agent is underperforming, the first question
is not which framework, which tool, or which orchestration pattern. It is: **has anyone
actually written down the rules the agent is supposed to be following?** In most
organisations the answer is that the rules live in the head of the person who has done the
job for nine years. Extracting them into thirteen numbered clauses is unglamorous, it looks
nothing like AI work, and on this dataset it was worth more than everything else combined.

**And a second one, which nearly caught me.** The instruction *"cite the path of every file
the decision rests on"* was unenforced — a sentence in a prompt, with nothing checking that it
was obeyed. Across five runs that all carried it, the number of packets citing **nothing at
all** was 0, then 2, then 5, then 1, then 7. Same instruction, same retrieval, same files
opened, same amounts. Nothing errored. Resolution accuracy was identical on almost every one.

I initially wrote this up as a lever breaking citations, because two rungs in a row looked
like a clean cause. The next run falsified it, and the truth was worse: **the property that
makes a review packet auditable was a coin flip nobody was watching.** If this ladder had
tracked only resolution accuracy, it would have shipped a configuration that recommends
payments citing no evidence, on a fifth to a third of the queue, and every dashboard would
have been green.

So the harness now checks it instead of asking for it — and the fix returned something I did
not design it to find. On one case the model produced an approval with an empty rationale, no
defects, no citations, and **zero tool calls**: it had answered from the one-line invoice
summary in the prompt without opening a single file, and the invoice was a duplicate. That
parses. Nothing errors. It scores as a false approval and nothing in the system objects. When
the check bounced it back for paths, it went and read the evidence, found the prior paid
invoice, and reversed itself — *"I must correct my earlier verdict rather than merely
re-cite it."*

The lesson generalises past citations: **an empty provenance field is not a formatting
problem, it is sometimes an honest report that no work was done.** Requiring a system to show
where an answer came from is not paperwork on top of the answer. On the answers that have no
source, it is the only thing standing between a plausible sentence and a wire transfer.

Score the property you promised, not the one you are optimising. Enforce it in the harness,
because an instruction nobody checks is a hope with good grammar. And when a metric you are
not optimising moves, **run it again before you explain it** — a story that fits one run is
not a finding.

---

## Repository

| | |
| --- | --- |
| `REPRODUCTION.md` | clean-machine guide — one command, no credential |
| `CHANGELOG.md` | the improvement changelog, each entry tied to a measurement |
| `policy/ap_policy.md` | AP-POL-2026-03, the shared source of truth |
| `cases/` | 24 synthetic cases; `expected.json` is ground truth and is never shown |
| `runs/recorded/` | committed trajectories — every number above re-derives from these |
| `make_counterfactual.py` | rebuilds the check-off run that measures the v6 lever, offline |
| `out/packets/` | the human review packets |
| `serve.py` + `webapp/` | the local console — `python serve.py`, replay by default, stdlib only |
| `build_static.py` | pre-renders the replay half of that console for GitHub Pages |
| `LICENSE` | MIT |

---

## Licence

MIT — see [`LICENSE`](LICENSE). That covers the code and the dataset alike: the 24 cases, the
correspondence, the contracts and AP-POL-2026-03 are all synthetic and hand-authored for this
project. Every vendor, invoice number, email and price in `cases/` is invented. No real
supplier, customer or invoice appears anywhere in this repository, and none of it is derived
from any employer's data.

Take the cases and score your own agent against them if they are useful to you — that is
rather the point of publishing ground truth.
