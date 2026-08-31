#!/usr/bin/env python3
"""Pre-render the ClearQueue console as a static site.

Why this exists
---------------
`serve.py` is a real server: it re-runs cases against the model, writes an approval log, and
serves the console over loopback. GitHub Pages runs no Python, so a hosted copy can only ever
be the *replay* half of the console -- the half that reads committed trajectories. That half
happens to be the half a judge needs: the queue, every case, every evidence file, every
recorded trajectory, the review packets, the ladder table with its controls, and the ground
truth behind the Reveal button.

The design constraint that shaped this file: **do not touch the console's source.**
`app.js` and `style.css` are copied byte for byte. `index.html` gets exactly two path edits
(`/static/x` -> `static/x`, so it survives a project-site subpath like `/clearqueue/`) plus an
injected preamble that overrides `window.fetch`. Every `/api/...` call `app.js` makes is
answered from a JSON file on disk instead of a handler. The console does not know it is being
replayed, and the running server keeps working exactly as before.

What is honestly missing, and says so on screen
----------------------------------------------
- "Run it now" (live *and* mock). Live needs a credential, which must never be published;
  mock needs the Python harness. The button is intercepted and explains itself.
- The approval gate writes `out/approvals.jsonl`. A static host has nothing to write to, so
  the POST returns an error the console already knows how to display.

Nothing here invents data. Every payload is produced by calling the same functions `serve.py`
calls, so the hosted numbers cannot drift from the served ones.

Publishing, once:

    git worktree add --orphan -b gh-pages ..\\clearqueue-pages
    python build_static.py --out ..\\clearqueue-pages
    cd ..\\clearqueue-pages && git add -A && git commit -m "Static replay" && git push -u origin gh-pages

and thereafter the middle three lines again. `main` is never checked out or touched.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import serve

ROOT = Path(__file__).resolve().parent

# The fetch shim. Injected into the *copy* of index.html, above the app.js tag, so app.js is
# never edited. It maps the server's route table onto a directory of files; the mapping below
# is the mirror image of `Handler.route_get` in serve.py.
SHIM = r"""
<!-- ===================== static-replay shim =====================
     Added by build_static.py. Not part of the console: app.js and style.css are byte-identical
     to the repository. This block answers the console's /api/ calls from files instead of a
     Python handler, so the page behaves the same without a server behind it. -->
<script>
(function () {
  var BASE = location.pathname.replace(/[^/]*$/, '');   // works at / and at /<repo>/
  var DEFAULT_RUN = '__DEFAULT_RUN__';
  var NEEDS_SERVER =
    'This is a static replay on GitHub Pages. Re-running a case and signing an approval ' +
    'need the Python server: clone the repo and run "python serve.py". Everything else on ' +
    'this page -- every trajectory, packet, evidence file and score -- is the committed run.';

  var realFetch = window.fetch.bind(window);

  function reply(obj) {
    return Promise.resolve(new Response(JSON.stringify(obj), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    }));
  }

  window.fetch = function (input, init) {
    var url = (typeof input === 'string') ? input : (input && input.url) || String(input);
    if (url.indexOf('/api/') !== 0) return realFetch(input, init);

    var method = ((init && init.method) || 'GET').toUpperCase();
    if (method !== 'GET') return reply({ error: NEEDS_SERVER });

    var cut = url.indexOf('?');
    var path = (cut < 0) ? url : url.slice(0, cut);
    var qs = new URLSearchParams((cut < 0) ? '' : url.slice(cut + 1));
    var run = qs.get('run') || DEFAULT_RUN;
    var file = null;

    if (path === '/api/bootstrap')            file = 'api/bootstrap.json';
    else if (path === '/api/ladder')          file = 'api/ladder.json';
    else if (path === '/api/approvals')       file = 'api/approvals.json';
    else if (path === '/api/queue')           file = 'api/queue/' + run + '.json';
    else if (path.indexOf('/api/case/') === 0)
      file = 'api/case/' + run + '/' + path.slice('/api/case/'.length) + '.json';
    else if (path.indexOf('/api/truth/') === 0)
      file = 'api/truth/' + path.slice('/api/truth/'.length) + '.json';
    else if (path.indexOf('/api/evidence/') === 0)
      // Served as text, exactly as the evidence viewer expects; no JSON fallback wanted here.
      return realFetch(BASE + 'api/evidence/' + path.slice('/api/evidence/'.length));
    else if (path.indexOf('/api/job/') === 0)
      return reply({ status: 'error', error: NEEDS_SERVER });

    if (!file) return reply({ error: 'no static route for ' + path });
    return realFetch(BASE + file).then(function (r) {
      return r.ok ? r : reply({ error: 'not in this static build: ' + path });
    });
  };

  /* The run button, intercepted in the capture phase so app.js's own handler never fires.
     Letting it fire would work -- the shim would answer with an error and the console would
     print it -- but it would first claim to be starting a run. Better to say no up front. */
  document.addEventListener('click', function (e) {
    var t = e.target;
    var hit = t && t.closest && t.closest('#runBtn');
    if (!hit) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    var note = document.getElementById('modeNote');
    if (note) note.innerHTML = '<div class="alert warn"><b>Not available on the hosted copy.</b> '
      + NEEDS_SERVER + '</div>';
  }, true);
})();
</script>
"""

BANNER = """  <div class="gatebanner" style="background:rgba(124,196,255,0.07);
       border-color:rgba(124,196,255,0.3);color:#bfe0ff">
    <b>Static replay.</b> This is the console reading the trajectories committed in the
    repository &mdash; the same data <code>python serve.py</code> shows. Re-running a case and
    signing an approval need the Python server and are disabled here.
  </div>
"""


def dump(path: Path, payload) -> int:
    """Write one JSON payload. Returns bytes, so the build can report its own size."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False)
    path.write_text(text, encoding="utf-8")
    return len(text.encode("utf-8"))


def build(out: Path) -> None:
    runs = serve.list_runs()
    cases = sorted(serve.truth())
    if not runs or not cases:
        raise SystemExit("nothing to build: runs/recorded/ or cases/ is empty")

    if out.exists():
        # Wipe the contents, not the directory. The intended output is a `gh-pages` worktree,
        # and its `.git` file is what makes it one -- deleting the directory outright would
        # leave a worktree git still believes in but can no longer find.
        for child in out.iterdir():
            if child.name == ".git":
                continue
            shutil.rmtree(child) if child.is_dir() else child.unlink()
    else:
        out.mkdir(parents=True)

    # ---- the shell -------------------------------------------------------------------
    # app.js and style.css are copied, never rewritten. Only index.html is touched, and only
    # for the two absolute paths that a project-site subpath would break.
    (out / "static").mkdir()
    shutil.copyfile(ROOT / "webapp" / "app.js", out / "static" / "app.js")
    shutil.copyfile(ROOT / "webapp" / "style.css", out / "static" / "style.css")

    html = (ROOT / "webapp" / "index.html").read_text(encoding="utf-8")
    for before, after in (('href="/static/style.css"', 'href="static/style.css"'),
                          ('src="/static/app.js"', 'src="static/app.js"')):
        if before not in html:
            raise SystemExit(f"index.html no longer contains {before!r}; update build_static.py")
        html = html.replace(before, after)

    marker = '<script src="static/app.js"></script>'
    html = html.replace(marker, SHIM.replace("__DEFAULT_RUN__", serve.DEFAULT_RUN) + marker)
    html = html.replace('  <nav class="tabs">', BANNER + '  <nav class="tabs">', 1)
    (out / "index.html").write_text(html, encoding="utf-8")

    # Pages runs Jekyll otherwise, which silently drops paths beginning with an underscore.
    (out / ".nojekyll").write_text("", encoding="utf-8")

    # ---- the API, frozen -------------------------------------------------------------
    # Handler.bootstrap / .queue / .case_detail touch no instance state, so they are called
    # unbound. That is deliberate: duplicating their bodies here would let the hosted payloads
    # drift away from the served ones without anything failing.
    boot = serve.Handler.bootstrap(None)
    boot["credential"] = {
        "available": False,
        "portable": False,
        "source": "static replay -- no server, and no API key is published with a static site",
    }
    total = dump(out / "api" / "bootstrap.json", boot)

    total += dump(out / "api" / "ladder.json", {
        "controls": [serve.summary_only(serve.score_control(s))
                     for s in ("always_approve", "always_hold", "always_escalate")],
        "runs": [serve.summary_only(serve.score_recorded(r)) for r in runs],
    })
    total += dump(out / "api" / "approvals.json", {"decisions": []})

    for run in runs:
        total += dump(out / "api" / "queue" / f"{run}.json", serve.Handler.queue(None, run))
        for case_id in cases:
            total += dump(out / "api" / "case" / run / f"{case_id}.json",
                          serve.Handler.case_detail(None, case_id, run))

    for case_id in cases:
        total += dump(out / "api" / "truth" / f"{case_id}.json", serve.truth()[case_id])

    # ---- evidence --------------------------------------------------------------------
    # Same exclusion the server enforces: expected.json is reachable only from /api/truth/,
    # which is what the Reveal button calls. evidence_files() already drops it.
    files = 0
    for case_id in cases:
        for rel in serve.evidence_files(case_id):
            src = serve.CASES / case_id / rel
            dst = out / "api" / "evidence" / case_id / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            total += src.stat().st_size
            files += 1

    written = sum(1 for p in out.rglob("*") if p.is_file())
    print(f"built {out}")
    print(f"  {len(runs)} runs x {len(cases)} cases -> {len(runs) * len(cases)} case payloads")
    print(f"  {files} evidence files, {written} files total, {total / 1_048_576:.2f} MB")
    print(f"  default run: {serve.DEFAULT_RUN}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Pre-render the console for static hosting.")
    ap.add_argument("--out", default="../clearqueue-pages",
                    help="output directory; contents are rebuilt, .git is left alone "
                         "(default: ../clearqueue-pages)")
    args = ap.parse_args()
    build(Path(args.out).resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
