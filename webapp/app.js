/* ClearQueue console.
   Plain DOM, no framework. Every number rendered here comes from the same score.py the CLI
   calls; nothing is recomputed in the browser except formatting. */

'use strict';

const $  = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const state = {
  boot: null,
  run: null,
  queue: null,
  caseId: null,
  detail: null,
  truthShown: false,
  job: null,
};

/* One-line notes for rows the version registry does not describe, because they are not
   rungs of the ladder -- they are measurement apparatus. */
const ROW_NOTES = {
  'v3-rerun-unenforced':
    'v3 again, unchanged. Run twice on purpose: citations came back 100.0% then 71.4%, ' +
    'which is what exposed the instruction as unenforced.',
  'v6-counterfactual-no-check':
    'Not a run. The final trajectories with the citation check rolled back, so the lever is ' +
    'the only difference.',
};

const DISP_CLASS = {
  APPROVE_FOR_PAYMENT: 'approve',
  SHORT_PAY: 'shortpay',
  HOLD_PRICE_VARIANCE: 'hold',
  HOLD_QUANTITY_VARIANCE: 'hold',
  DUPLICATE_REJECT: 'duplicate',
  ESCALATE_HUMAN: 'escalate',
};

/* ---------------------------------------------------------------- utilities */

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const money = (n, cur) =>
  (typeof n === 'number')
    ? n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) +
      (cur ? ' ' + cur : '')
    : '—';

const pill = (disp) =>
  `<span class="pill ${DISP_CLASS[disp] || 'none'}">${esc(disp || 'NO VERDICT')}</span>`;

const bar = (pct, kind = '') =>
  `<div class="bar"><i class="${kind}" style="width:${Math.max(0, Math.min(100, pct))}%"></i></div>`;

async function api(path, opts) {
  const res = await fetch(path, opts);
  const data = await res.json();
  if (data && data.error && !opts?.tolerateError) throw new Error(data.error);
  return data;
}

async function postJSON(path, body) {
  return api(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    tolerateError: true,
  });
}

/* ------------------------------------------------- a very small markdown renderer
   Packets are the signable artifact, so they are rendered rather than dumped as text.
   This covers exactly what packet.py emits: headings, tables, lists, checkboxes, rules,
   blockquotes, bold, inline code, and the <sub> footer. Nothing else is supported and
   nothing else appears. */

function markdown(src) {
  const inline = (t) => esc(t)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
    .replace(/&lt;sub&gt;(.*?)&lt;\/sub&gt;/g, '<sub>$1</sub>')
    .replace(/&lt;br&gt;/g, '<br>');

  const out = [];
  const lines = String(src).split('\n');
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];

    if (/^\s*$/.test(line)) { i++; continue; }
    if (/^---+\s*$/.test(line)) { out.push('<hr>'); i++; continue; }

    let m = line.match(/^(#{1,4})\s+(.*)$/);
    if (m) { const n = m[1].length; out.push(`<h${n}>${inline(m[2])}</h${n}>`); i++; continue; }

    if (line.startsWith('|')) {                       // table
      const rows = [];
      while (i < lines.length && lines[i].startsWith('|')) { rows.push(lines[i]); i++; }
      const cells = (r) => r.replace(/^\||\|$/g, '').split('|').map((c) => c.trim());
      const isSep = (r) => /^[\s|:-]+$/.test(r);
      const head = isSep(rows[1] || '') ? cells(rows[0]) : null;
      const bodyRows = rows.slice(head ? 2 : 0).filter((r) => !isSep(r));
      let t = '<table>';
      if (head && head.some((c) => c)) {
        t += '<thead><tr>' + head.map((c) => `<th>${inline(c)}</th>`).join('') + '</tr></thead>';
      }
      t += '<tbody>' + bodyRows.map((r) =>
        '<tr>' + cells(r).map((c) => `<td>${inline(c)}</td>`).join('') + '</tr>').join('') +
        '</tbody></table>';
      out.push(t);
      continue;
    }

    if (/^\s*[-*]\s/.test(line)) {                    // list, incl. [ ] checkboxes
      const items = [];
      while (i < lines.length && /^\s*[-*]\s/.test(lines[i])) {
        let text = lines[i].replace(/^\s*[-*]\s/, '');
        const box = text.match(/^\[( |x|X)\]\s*(.*)$/);
        items.push(box
          ? `<li><input type="checkbox" disabled${box[1] !== ' ' ? ' checked' : ''}> ${inline(box[2])}</li>`
          : `<li>${inline(text)}</li>`);
        i++;
      }
      out.push('<ul>' + items.join('') + '</ul>');
      continue;
    }

    if (line.startsWith('>')) {
      const quote = [];
      while (i < lines.length && lines[i].startsWith('>')) {
        quote.push(lines[i].replace(/^>\s?/, '')); i++;
      }
      out.push(`<blockquote>${inline(quote.join(' '))}</blockquote>`);
      continue;
    }

    const para = [];
    while (i < lines.length && !/^\s*$/.test(lines[i]) && !/^[#|>-]/.test(lines[i])) {
      para.push(lines[i]); i++;
    }
    if (para.length) out.push(`<p>${inline(para.join(' '))}</p>`);
    else i++;
  }
  return out.join('\n');
}

/* ---------------------------------------------------------------- navigation */

function showView(name) {
  $$('nav.tabs button').forEach((b) => b.classList.toggle('on', b.dataset.view === name));
  $$('.view').forEach((v) => v.classList.toggle('on', v.id === `view-${name}`));
}

/* ---------------------------------------------------------------- queue */

function renderQueueCards(s) {
  const overpay = s.overpay_exposure;
  $('#queueCards').innerHTML = `
    <div class="card"><div class="k">Exceptions triaged</div>
      <div class="v">${s.n}</div><div class="n">${s.produced} produced a verdict</div></div>
    <div class="card"><div class="k">Resolution accuracy</div>
      <div class="v good">${s.resolution_accuracy}%</div>
      <div class="n">disposition <i>and</i> amount to the cent</div></div>
    <div class="card"><div class="k">False approvals</div>
      <div class="v ${s.false_approvals ? 'warn' : 'good'}">${s.false_approvals}/${s.non_approve_cases}</div>
      <div class="n">the error that costs money</div></div>
    <div class="card"><div class="k">Overpayment exposure</div>
      <div class="v ${overpay > 0 ? 'warn' : 'good'}">$${money(overpay)}</div>
      <div class="n">if every line were paid as recommended</div></div>
    <div class="card"><div class="k">Evidence cited</div>
      <div class="v ${s.citation_validity === 100 ? 'good' : 'warn'}">${s.citation_validity}%</div>
      <div class="n">decisive file named, harness-checked</div></div>
    <div class="card"><div class="k">Cost</div>
      <div class="v">$${(s.cost_usd / s.n).toFixed(4)}</div>
      <div class="n">per exception, ${s.tool_calls} tool calls total</div></div>
    <div class="card"><div class="k">Human time</div>
      <div class="v">${Math.round(s.n * 8.5)} min</div>
      <div class="n">saved vs. 11 min each, at 2.5 min to review a packet</div></div>`;
}

function renderQueueTable(rows) {
  const tb = $('#queueTable tbody');
  tb.innerHTML = rows.map((r) => {
    const ok = r.resolved;
    const verdictCell = r.false_approval
      ? '<span class="cross">&#10007; false approval</span>'
      : ok ? '<span class="tick">&#10003; correct</span>'
           : `<span class="cross">&#10007;</span> <span class="dim small">truth: ${esc(r.true_disposition)}</span>`;
    const cites = (r.citations || []).length
      ? r.citations.map((c) => `<span class="chip">${esc(c)}</span>`).join('')
      : '<span class="dim small">none</span>';
    return `<tr class="click" data-case="${esc(r.case_id)}">
      <td class="mono">${esc(r.case_id)}</td>
      <td>${esc(r.vendor)}</td>
      <td class="mono small">${esc(r.invoice_number)}<br><span class="dim">${esc(r.po_number)}</span></td>
      <td class="num">${money(r.billed, r.currency)}</td>
      <td>${pill(r.predicted)}${(r.defects || []).length
        ? `<div class="dim small" style="margin-top:3px">${r.defects.length} defect${r.defects.length > 1 ? 's' : ''}</div>` : ''}</td>
      <td class="num">${money(r.payable_amount)}</td>
      <td class="mono small">${esc(r.required_approver_role)}</td>
      <td class="num">${r.tool_calls}</td>
      <td style="max-width:230px">${cites}</td>
      <td class="small">${verdictCell}</td>
    </tr>`;
  }).join('');

  $$('#queueTable tbody tr').forEach((tr) => {
    tr.onclick = () => { openCase(tr.dataset.case); showView('case'); };
  });
}

async function loadQueue(run) {
  state.run = run;
  state.queue = await api(`/api/queue?run=${encodeURIComponent(run)}`);
  renderQueueCards(state.queue.summary);
  renderQueueTable(state.queue.rows);
  const sel = $('#caseSelect');
  sel.innerHTML = state.queue.rows.map((r) =>
    `<option value="${esc(r.case_id)}">${esc(r.case_id)} — ${esc(r.vendor)}</option>`).join('');
}

/* ---------------------------------------------------------------- case detail */

async function openCase(caseId) {
  state.caseId = caseId;
  state.truthShown = false;
  $('#caseSelect').value = caseId;
  $('#runStatus').textContent = '';
  $('#modeNote').innerHTML = '';
  state.detail = await api(`/api/case/${encodeURIComponent(caseId)}?run=${encodeURIComponent(state.run)}`);
  renderCase(state.detail);
}

function renderCase(d) {
  const v = d.verdict || {};
  const cited = new Set((v.citations || []).map((c) => c.replace(/\\/g, '/')));
  const read = new Set(d.stats.files_read || []);

  /* file list */
  $('#fileList').innerHTML = d.evidence.map((f) => {
    const flag = cited.has(f) ? '<span class="flag cited">CITED</span>'
      : read.has(f) ? '<span class="flag read">opened</span>' : '';
    return `<li data-file="${esc(f)}"><span>${esc(f)}</span>${flag}</li>`;
  }).join('');
  $$('#fileList li').forEach((li) => { li.onclick = () => openFile(d.case_id, li.dataset.file); });

  /* invoice header */
  const inv = d.invoice || {};
  const fields = [
    ['Vendor', inv.vendor_name_as_billed], ['Invoice', inv.invoice_number],
    ['Date', inv.invoice_date], ['PO', inv.po_number],
    ['Billed', money(inv.gross_amount, inv.currency)],
    ['Service period', inv.service_period],
  ].filter(([, val]) => val != null && val !== '');
  $('#invoiceKv').innerHTML = fields.map(([k, val]) =>
    `<dt>${esc(k)}</dt><dd>${esc(val)}</dd>`).join('');

  renderVerdict(d);
  $('#packetPane').innerHTML = d.packet
    ? markdown(d.packet)
    : '<p class="dim">No packet on disk for this case yet.</p>';
  renderTrace(d.events, d.stats);
  renderGate(d);

  /* open the decisive file by default so the case reads as a story, not a form */
  const first = (v.citations || [])[0] || d.evidence[0];
  if (first) openFile(d.case_id, first.replace(/\\/g, '/'));
}

function renderVerdict(d) {
  const v = d.verdict || {};
  const sc = d.score || {};
  const meta = v._meta || {};
  const defects = (v.defects || []).map((x) => `<span class="chip">${esc(x)}</span>`).join('') ||
    '<span class="dim small">none</span>';

  $('#verdictPane').innerHTML = `
    <div class="verdictbox">
      <div>${pill(v.disposition)}</div>
      <div class="amt">${money(v.payable_amount, v.currency)}</div>
      <div class="small muted">payable if approved &middot; requires
        <code>${esc(v.required_approver_role || 'n/a')}</code></div>
      <div style="margin-top:10px">${defects}</div>
      <div class="rationale">${esc(v.rationale || '')}</div>
      <div class="small dim" style="margin-top:10px">
        ${meta.tool_calls ?? 0} tool calls &middot;
        ${meta.input_tokens?.toLocaleString?.() ?? 0} in / ${meta.output_tokens?.toLocaleString?.() ?? 0} out &middot;
        $${(meta.cost_usd ?? 0).toFixed(4)} &middot; ${meta.latency_s ?? 0}s
      </div>
    </div>
    <div id="truthSlot">${state.truthShown ? truthHTML(sc) : ''}</div>`;
}

function truthHTML(sc) {
  const hit = sc.resolved;
  return `<div class="truthbox ${hit ? 'hit' : 'miss'}">
    <div class="small muted" style="margin-bottom:4px">Ground truth &mdash; hand-authored before any
      run, never shown to the agent</div>
    <div>${pill(sc.true_disposition)} ${hit
      ? '<span class="tick">&#10003; disposition and amount both correct to the cent</span>'
      : '<span class="cross">&#10007; missed</span>'}</div>
    ${sc.false_approval ? '<div class="cross small" style="margin-top:6px">This is a false approval &mdash; ' +
      'the error direction that costs money.</div>' : ''}
    ${sc.overpay ? `<div class="small" style="margin-top:4px">Overpayment exposure $${money(sc.overpay)}</div>` : ''}
    ${sc.underpay ? `<div class="small" style="margin-top:4px">Underpayment exposure $${money(sc.underpay)}</div>` : ''}
    <div class="small ${sc.citation_ok ? 'muted' : 'cross'}" style="margin-top:4px">
      Decisive evidence cited: ${sc.citation_ok ? 'yes' : 'no'}</div>
  </div>`;
}

/* ---------------------------------------------------------------- trajectory */

function eventLabel(e) {
  switch (e.type) {
    case 'case_start':
      return [`triage opened on <b>${esc(e.case_id)}</b> &middot; ${esc(e.version)}`,
              `levers: ${(e.levers || []).join(', ')}`];
    case 'instructions':
      return ['system prompt and tools handed to the model',
              `TOOLS\n${(e.tools || []).join(', ')}\n\nSYSTEM\n${e.system}\n\nUSER\n${e.user_prompt}`];
    case 'thinking':
      return ['reasoning', e.summary || ''];
    case 'tool_call':
      return [`called <b>${esc(e.tool)}</b>${e.input?.path ? ' &rarr; ' + esc(e.input.path) : ''}`,
              JSON.stringify(e.input, null, 2)];
    case 'tool_result':
      return [`<span class="dim">${esc(e.tool)} returned${e.is_error ? ' an error' : ''}</span>`,
              JSON.stringify(e.output, null, 2)];
    case 'final_message':
      return [`answered (stop: ${esc(e.stop_reason)})`, e.text || ''];
    case 'citation_rejected':
      return [`<b>harness rejected the verdict</b> &mdash; ${esc(e.problem)}`,
              'The check is in the harness, not the prompt. An unenforced instruction is not ' +
              'a property of the system, it is a hope.'];
    case 'citation_retry_applied':
      return [`re-ask resolved: ${e.resolved ? 'yes' : 'no'}` +
              (e.verdict_moved ? ' &mdash; <b>and the answer itself changed</b>' : ' (answer unchanged)'),
              `before: ${JSON.stringify(e.before)}\nafter:  ${JSON.stringify(e.after)}`];
    case 'verifier_call': return ['independent verifier pass started', ''];
    case 'verifier_result':
      return [e.confirmed ? 'verifier confirmed the arithmetic' : 'verifier objected',
              JSON.stringify(e, null, 2)];
    case 'revision_requested': return ['revision requested', (e.issues || []).join('\n')];
    case 'revision_applied':
      return [`revision applied &mdash; verdict changed: ${e.changed ? 'yes' : 'no'}`,
              JSON.stringify(e, null, 2)];
    case 'verdict':
      return [`<b>final verdict</b> &mdash; ${esc(e.disposition)} at ${money(e.payable_amount)}`,
              JSON.stringify(e, null, 2)];
    default:
      return [esc(e.type), JSON.stringify(e, null, 2)];
  }
}

const FLAGGED = new Set(['citation_rejected', 'citation_retry_applied', 'revision_requested',
                         'revision_applied', 'verifier_result']);

function renderTrace(events, stats) {
  let notes = '';
  if (stats.citation_rejected) {
    notes += `<div class="alert warn"><b>The citation check fired on this case.</b>
      The first answer named no usable evidence, so the harness refused it and asked again.
      Watch what the second pass does &mdash; on one case in this queue it did not just add a
      citation, it changed the decision.</div>`;
  }
  if (stats.tool_calls === 0) {
    notes += `<div class="alert bad"><b>Zero tool calls on the first pass.</b>
      The model answered without opening a single file. An empty citations array here was not a
      formatting lapse &mdash; it was an accurate report that no work had been done.</div>`;
  }

  $('#tracePane').innerHTML = notes + '<ul class="timeline">' + events.map((e) => {
    const [label, detail] = eventLabel(e);
    return `<li class="ev ${esc(e.type)}${FLAGGED.has(e.type) ? ' flagged' : ''}">
      <div class="head"><span class="ty">${esc(e.type)}</span><span class="lbl">${label}</span></div>
      ${detail ? `<div class="detail">${esc(detail)}</div>` : ''}
    </li>`;
  }).join('') + '</ul>';

  $$('#tracePane .ev .head').forEach((h) => {
    h.onclick = () => h.parentElement.classList.toggle('open');
  });
}

/* ---------------------------------------------------------------- approval gate */

function renderGate(d) {
  const v = d.verdict || {};
  $('#gatePane').innerHTML = `
    <p class="small muted" style="margin-top:0">
      ClearQueue has released no funds and cannot. Signing here records a decision; it does not
      move money.</p>
    <label class="field" for="reviewerName">Reviewer name (required)</label>
    <input type="text" id="reviewerName" placeholder="e.g. A. Okafor, AP Manager" style="width:100%">
    <label class="field" style="margin-top:10px" for="reviewNote">Note (optional)</label>
    <textarea id="reviewNote" rows="2" style="width:100%" placeholder="Why you agreed or did not"></textarea>
    <div class="row" style="margin-top:12px">
      <button class="btn good" data-decision="APPROVED">Approve as recommended</button>
      <button class="btn bad" data-decision="REJECTED">Reject</button>
      <button class="btn warn" data-decision="ESCALATED">Escalate</button>
    </div>
    <div id="gateResult" class="small" style="margin-top:10px"></div>`;

  $$('#gatePane button[data-decision]').forEach((b) => {
    b.onclick = async () => {
      const res = await postJSON('/api/approve', {
        case_id: d.case_id, run: d.run,
        recommended: v.disposition, recommended_amount: v.payable_amount,
        required_approver_role: v.required_approver_role,
        decision: b.dataset.decision,
        reviewer: $('#reviewerName').value,
        note: $('#reviewNote').value,
      });
      $('#gateResult').innerHTML = res.error
        ? `<span class="cross">${esc(res.error)}</span>`
        : `<span class="tick">Recorded &mdash; ${esc(res.recorded.human_decision)} by
           ${esc(res.recorded.reviewer)} at ${esc(res.recorded.decided_at)}.</span>
           <span class="dim">${res.total} decision${res.total > 1 ? 's' : ''} in the log.</span>`;
      loadApprovals();
    };
  });
}

/* ---------------------------------------------------------------- evidence viewer */

async function openFile(caseId, relpath) {
  $$('#fileList li').forEach((li) => li.classList.toggle('on', li.dataset.file === relpath));
  $('#fileTitle').textContent = relpath;
  const res = await fetch(`/api/evidence/${encodeURIComponent(caseId)}/${relpath}`);
  const text = await res.text();
  let pretty = text;
  if (relpath.endsWith('.json')) {
    try { pretty = JSON.stringify(JSON.parse(text), null, 2); } catch { /* show it raw */ }
  }
  $('#fileBody').textContent = pretty;
}

/* ---------------------------------------------------------------- live / mock run */

async function startRun() {
  const mode = $('#modeSelect').value;
  const caseId = state.caseId;

  if (mode === 'live' && !state.boot.credential.available) {
    $('#modeNote').innerHTML = `<div class="alert bad">No credential is configured, so a live
      run is not possible. Replay and mock still work. ${esc(state.boot.credential.source)}</div>`;
    return;
  }
  if (mode === 'mock') {
    $('#modeNote').innerHTML = `<div class="alert warn"><b>Mock mode is the always-approve
      control, by design.</b> It approves every invoice at the billed amount and cites nothing.
      A mock run must score exactly what <code>score.py --controls</code> reports for
      <code>always_approve</code> &mdash; <code>verify.py</code> asserts that equality, and it is
      the only thing a mock run can tell you. It exercises the harness; it does not
      demonstrate the agent.</div>`;
  } else {
    $('#modeNote').innerHTML = `<div class="alert info">Live run against
      <code>${esc(state.boot.credential.source)}</code>. Same call path as
      <code>python run.py --version final --llm anthropic</code> &mdash; there is no demo-only
      shortcut. Output lands in <code>runs/_webapp/</code>, never in the committed
      <code>runs/recorded/</code>.</div>`;
  }

  $('#runBtn').disabled = true;
  $('#runStatus').innerHTML = '<span class="spin"></span> starting&hellip;';
  const { job_id } = await postJSON('/api/triage', { case_id: caseId, mode, version: 'final' });
  state.job = job_id;
  pollJob(job_id);
}

async function pollJob(jobId) {
  const job = await api(`/api/job/${jobId}`, { tolerateError: true });
  if (job.events && job.events.length) {
    renderTrace(job.events, job.stats);
    $('#runStatus').innerHTML =
      `<span class="spin"></span> ${job.events.length} events &middot; ${job.stats.tool_calls} tool calls`;
  }
  if (job.status === 'running') { setTimeout(() => pollJob(jobId), 700); return; }

  $('#runBtn').disabled = false;
  if (job.status === 'error') {
    $('#runStatus').innerHTML = `<span class="cross">${esc(job.error)}</span>`;
    return;
  }
  $('#runStatus').innerHTML = '<span class="tick">&#10003; finished</span>';

  /* Show the freshly produced verdict, and say plainly that it is live output rather than
     the committed trace, so nobody mistakes one for the other on a recording. */
  const live = { ...state.detail, verdict: job.verdict, events: job.events, stats: job.stats };
  live.score = null;
  renderVerdict({ ...live, score: state.detail.score });
  $('#verdictPane').insertAdjacentHTML('afterbegin',
    `<div class="alert info">Just produced live. The committed trace for this case is still in
     <code>runs/recorded/${esc(state.run)}/</code>; reload the case to go back to it.</div>`);
}

/* ---------------------------------------------------------------- ladder */

async function loadLadder() {
  const d = await api('/api/ladder');
  const versions = Object.fromEntries(state.boot.versions.map((v) => [v.name, v]));

  $('#controlTable tbody').innerHTML = d.controls.map((c) => `<tr class="control">
    <td class="mono">${esc(c.label.replace('control/', ''))}</td>
    <td class="num">${c.resolution_accuracy}%</td>
    <td class="num">${c.false_approvals}/${c.non_approve_cases}</td>
    <td class="num">$${money(c.overpay_exposure)}</td>
    <td class="num">$${money(c.underpay_exposure)}</td>
    <td class="num">${c.citation_validity}%</td></tr>`).join('');

  $('#ladderTable tbody').innerHTML = d.runs.map((r) => {
    const note = ROW_NOTES[r.label] || versions[r.label]?.headline || '';
    const ship = r.label === 'final';
    return `<tr class="${ship ? 'ship' : ''}">
      <td class="mono">${esc(r.label)}${ship ? ' <span class="pill flat approve">ships</span>' : ''}</td>
      <td class="num">${r.resolution_accuracy}%</td>
      <td style="width:90px">${bar(r.resolution_accuracy, 'good')}</td>
      <td class="num">${r.false_approvals}/${r.non_approve_cases}</td>
      <td class="num">$${money(r.overpay_exposure)}</td>
      <td class="num">${r.citation_validity}%</td>
      <td style="width:90px">${bar(r.citation_validity, r.citation_validity === 100 ? 'good' : 'bad')}</td>
      <td class="num">$${(r.cost_usd / r.n).toFixed(4)}</td>
      <td class="small muted" style="max-width:44ch">${esc(note)}</td>
    </tr>`;
  }).join('');

  $('#versionNotes').innerHTML = state.boot.versions.filter((v) => v.hypothesis).map((v) => `
    <div class="card">
      <div class="row"><span class="pill flat shortpay">${esc(v.name)}</span>
        <span class="small muted">${v.levers.map((l) => `<span class="chip">${esc(l)}</span>`).join('')}</span></div>
      <div style="margin-top:6px">${esc(v.headline)}</div>
      <div class="small muted" style="margin-top:6px"><b>Hypothesis before running it:</b>
        ${esc(v.hypothesis)}</div>
    </div>`).join('');
}

/* ---------------------------------------------------------------- approvals */

async function loadApprovals() {
  const d = await api('/api/approvals');
  const tb = $('#approvalTable tbody');
  if (!d.decisions.length) {
    tb.innerHTML = `<tr><td colspan="8" class="dim">No decisions recorded yet. Open a case and
      sign it in the approval gate.</td></tr>`;
    return;
  }
  tb.innerHTML = d.decisions.slice().reverse().map((r) => `<tr>
    <td class="mono small">${esc(r.decided_at)}</td>
    <td class="mono">${esc(r.case_id)}</td>
    <td>${pill(r.recommended)}</td>
    <td class="num">${money(r.recommended_amount)}</td>
    <td><span class="pill ${r.human_decision === 'APPROVED' ? 'approve'
      : r.human_decision === 'REJECTED' ? 'duplicate' : 'escalate'}">${esc(r.human_decision)}</span></td>
    <td>${esc(r.reviewer)}</td>
    <td class="small muted">${esc(r.note || '')}</td>
    <td class="mono small dim">${esc(r.trajectory)}</td></tr>`).join('');
}

/* ---------------------------------------------------------------- boot */

async function boot() {
  state.boot = await api('/api/bootstrap');

  $('#runSelect').innerHTML = state.boot.runs.map((r) =>
    `<option value="${esc(r)}"${r === state.boot.default_run ? ' selected' : ''}>${esc(r)}</option>`).join('');
  $('#runSelect').onchange = async (e) => {
    await loadQueue(e.target.value);
    if (state.caseId) openCase(state.caseId);
  };

  const c = state.boot.credential;
  $('#credBadge').innerHTML = c.available
    ? `credential: ${esc(c.source)}`
    : 'no credential &mdash; replay and mock only';
  $('#credBadge').title = c.available
    ? 'Live runs are possible. Replay needs no credential at all.'
    : String(c.source);

  $$('nav.tabs button').forEach((b) => { b.onclick = () => showView(b.dataset.view); });
  $('#caseSelect').onchange = (e) => openCase(e.target.value);
  $('#runBtn').onclick = startRun;
  $('#truthBtn').onclick = () => {
    state.truthShown = !state.truthShown;
    $('#truthBtn').textContent = state.truthShown ? 'Hide ground truth' : 'Reveal ground truth';
    $('#truthSlot').innerHTML = state.truthShown ? truthHTML(state.detail.score) : '';
  };

  await loadQueue(state.boot.default_run);
  await Promise.all([loadLadder(), loadApprovals()]);
  await openCase(state.queue.rows[0].case_id);
}

boot().catch((e) => {
  document.querySelector('main').innerHTML =
    `<div class="alert bad">Console failed to start: ${esc(e.message)}</div>`;
});
