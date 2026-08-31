# Video script — ClearQueue (target 4:45, hard limit 5:00)

Screen recording with voiceover. Everything shown is real: the console at
`http://127.0.0.1:8765` is a view over the committed trajectories and the same `solve_case()`
the CLI calls, and the closing shot is a real terminal. No slides beyond the two title cards.

> **Before recording**
>
> 1. `python serve.py` — leave it running. Browser at 1280×720 or wider, zoom 100%, browser
>    chrome minimised. Replay mode needs no credential; the live run in scene 3 does.
> 2. `Remove-Item out/approvals.jsonl` so the approval log starts empty and fills on camera.
> 3. Terminal (for the closing shot only) at ~110 columns, prompt shortened so no home
>    directory appears on screen: `function prompt { "PS clearqueue> " }`.
> 4. Nothing else visible — no other tabs, no bookmarks bar, no notifications.
>
> **Do not demo in mock mode.** The mock is the always-approve control by design; it approves
> every invoice at the billed amount and cites nothing. On camera it would show the agent
> paying duplicates at 41.7%. Replay is the default and shows the real 95.8% behaviour with
> real tool calls; the one live run in scene 3 proves the traces were not hand-made.

---

## 0:00–0:12 — Title card

> **ClearQueue** — an accounts-payable exception triage agent.
> micro1 Frontier Engineering Challenge 2026.

**Say:** "This is ClearQueue. It clears an accounts-payable exceptions queue. It never pays
anything, and I'll show you why that's structural rather than a promise."

---

## 0:12–1:15 — The problem (screen: console → **Exception queue**, then Case detail on CASE-002 and CASE-008)

**Open on the queue screen.** Twenty-four rows, the green banner across the top, the summary
cards. Let it sit for two seconds before speaking — the shape of the queue is the pitch.

**Say:**

"Amara works accounts payable. Two hundred supplier invoices a week. The ERP auto-matches
about seventy percent against the purchase order and the goods receipt, and those get paid
without anyone looking.

The other sixty land in an exceptions queue, and the exceptions queue is her.

Here's one." *(click CASE-002; in the evidence pane click `invoice.json`, then `po.json`)*
"Kestrel billed 480 EACH at two dollars. The PO says 40 CASE at twenty-four. Same goods — a
case is twelve — and it reconciles exactly. No rule caught it, because the pack size lives in
a vendor master field the matching engine doesn't read.

Here's another." *(case selector → CASE-008)* "Halcyon, five thousand one hundred and sixty
dollars, and there's an identical Halcyon invoice from three weeks ago. Same amount, same
PO, same vendor. It is *not* a duplicate — one covers February, one covers March. It's a
monthly service contract, and the policy says rejecting it is" *(read from the policy)*
"'a supplier-relationship failure, treated as seriously as an overpayment.'

And then there's the case that looks exactly like that one but where the service periods
*overlap*, and that one is a duplicate.

Here's the thing that makes this a job for an agent rather than for better rules: **every
invoice in that queue is there because the rules already failed on it.** That's what an
exception is. The deciding fact is almost never in the structured data — it's in a unit of
measure, or a sentence in a supplier email, or a contract clause."

---

## 1:15–1:45 — Why this problem (screen: still on CASE-008, click **Reveal ground truth**)

**Say:**

"I picked this over a coding-agent problem for one reason: **it has ground truth to the
cent.**

Every one of the twenty-four cases has a hand-authored correct disposition and a correct
payable amount." *(the truth panel opens under the recommendation)* "Written before any run,
never shown to the agent. The scorer is ordinary Python with no model in it. If the agent says
thirty-two thousand three hundred sixty-two fifty and the truth is fifty-one, it's wrong, and
no amount of convincing prose changes that.

Which also means every improvement claim I'm about to make is checkable — offline, in about
a second, with no API key."

---

## 1:45–2:55 — The demo (screen: Case detail on CASE-022, mode **live**, press *Run it now*)

**Say while it runs** — the trajectory pane fills event by event as the model works:

"This is the hard duplicate. Watch what it does: it lists the evidence, reads the vendor
master, finds the prior invoice, and then —" *(expand `duplicate_check` and
`compare_vendor_names` in the timeline)* "— it hands the arithmetic and the name
normalisation to deterministic calculators.

That division is the whole design. **The model decides; it does not calculate.** Which tool
to call and what the results mean together is judgment, and that's the model's job. Half-up
cent rounding, the lower of two percent and fifty dollars, netting credit memos before
reading the approval threshold — that's mechanical, and a language model doing it by hand
is a language model that's right *most* of the time."

**Then scroll to the review packet pane.**

**Say:**

"Every case ends here. The recommendation, the defects, the evidence it actually relied on,
the full computation audit — and a signature block.

This packet is rebuilt **from the recorded trajectory**, not from the agent's own summary of
itself. So if you don't trust the rationale, you can read what was actually computed. And if
a trajectory were ever too thin to reconstruct the decision, the packet would visibly
degrade instead of the gap going unnoticed."

**Then the approval gate on the right:** type a reviewer name, add a one-line note, click
**Reject**. Switch to the **Approval log** tab to show the row land.

**Say:**

"There is no payment code path in this project to disable. `payable_amount` is what gets
released *if* the approver named by clause ten signs. Every decision lands in
`approvals.jsonl` with a name, a UTC timestamp, and a link back to the trajectory that
produced the recommendation."

---

## 2:55–4:15 — What was measured (screen: console → **How it was built**)

**Say:**

"Six versions, same code path, different levers — there's no branch on version name
anywhere in the solve path, so a delta is attributable to the lever.

Read the controls first." *(the top table)* "Always-approve, always-hold,
always-escalate. No reasoning at all. Always-approve scores forty-one point seven percent on
this dataset. **That's the number everything has to beat before it has demonstrated
anything.**

v0 — no policy document, no schema — scores exactly forty-one point seven. Level with a
strategy that doesn't read the invoice.

v1 adds the written policy and a strict schema. Ninety-five point eight. **Plus fifty-four
points, same model, same evidence, same number of API calls, same cost per case.**

Now watch the rest of the ladder." *(run the cursor down the Resolved bars)* "Calculators.
Retrieval. A verifier. Vendor memory. Confidence gating. Six more rungs, up to six times the
cost per case — and the resolution number does not move again. Not once.

Three of those levers I cut after measuring them. The verifier raised three objections across
forty-eight invocations: two were wrong and the agent correctly refused them, one was wrong
and the agent accepted it, which turned a correct answer into an incorrect one. Zero real
errors caught, one introduced. It's gone.

But look at the citation column, because this is the part I did not plan." *(point at the
100.0 bar on `v3-evidence`, then the red 71.4 bar on `v3-rerun-unenforced`)* "That's v3. And
that's v3 again — same lever set, same code, same cases, run twice. One hundred percent, then
seventy-one. The instruction to cite your evidence was a sentence in a prompt, and nothing
ever checked it. Whether a packet you're being asked to sign carried its sources was a
property of the *run*.

So the last version puts the check in the harness: cite nothing, or cite a file that doesn't
exist, and you get asked once more. Back to a hundred percent.

And it found something I wasn't looking for." *(back to Case detail → CASE-007; the red
banner at the top of the trajectory pane reads "Zero tool calls on the first pass")* "This
case came back approved. Empty rationale, no defects, no citations — and **zero tool calls.**
It answered from the one-line summary in the prompt without opening a single file, and the
invoice was a duplicate. That parses. Nothing errors. It's a false approval and the system had
no objection to it.

The check bounced it back and asked for paths. Seven tool calls later it read the vendor
master, found the prior invoice already paid, and reversed itself." *(expand the `verdict`
event and read the rationale)* "*'I must correct my earlier verdict rather than merely re-cite
it.'*

An empty provenance field isn't always a formatting slip. Sometimes it's an honest report that
no work was done.

I want to be straight about the shape of this result, because it isn't the one I predicted."

---

## 4:15–4:45 — Hot take (screen: `CHANGELOG.md`, the v1 and v6 entries)

**Say:**

"So here's my hot take, and it's not a comfortable one for a hackathon about agents.

**Most of what gets called agent engineering is compensating for a specification that was
never written down.**

The tools, the retrieval, the verifier, the memory — none of it moved the accuracy number.
What moved it was thirteen numbered clauses in a markdown file. Plus fifty-four points, for
zero extra cost and zero extra latency.

That's not an argument that scaffolding is useless. The calculators and the retrieval both
survived, and they survived for a reason worth naming: **they bought auditability, not
accuracy.** For a system whose entire output is a recommendation a person has to sign, that
*is* the product. It just isn't what the accuracy column measures, and pretending otherwise
would have been the easy version of this writeup.

The corollary is the useful half. If your agent is underperforming, the first question isn't
which framework or which orchestration pattern. It's: **has anyone actually written down the
rules it's supposed to be following?** In most organisations those rules live in the head of
the person who's done the job for nine years. Extracting them looks nothing like AI work, and
here it was worth more than everything else combined.

And the second one, which nearly caught me: **score the property you promised, not the one
you're optimising.** I almost shipped a system that recommends payments citing no evidence,
because I was watching accuracy and accuracy never moved. And when a metric you're *not*
optimising moves — run it again before you explain it. I wrote a clean causal story about it
once. The next run falsified it, and that correction is in the changelog too."

---

## 4:45–4:55 — Close (screen: `python verify.py`)

**Say:**

"One command. No API key, no network, no installs — five stages, including the one that
matters: the mock run has to score *exactly* what the always-approve control scores,
because the mock *is* always-approve. If those two numbers ever separate, the harness is
inventing signal the model didn't produce.

Everything in this video reproduces from the committed trajectories. Thanks for watching."
