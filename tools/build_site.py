#!/usr/bin/env python3
"""Build the published evidence page from committed artifacts, by running them.

Plumbline's product is an artifact: a provenance-stamped report that a stranger
can check. A visitor cannot see one without cloning the repository and running
it, so this renders the committed audit as a page — and, because a page that
merely *described* the harness refusing would be the kind of claim this
repository exists to argue against, it **executes** the refusals at build time
and renders what actually happened.

Four things are run, in a temporary copy of the repository's own evidence:

1. the documented gate command, unchanged, which must reproduce the committed
   run id exactly (`--out audits`, `examples/riverbend.toml`);
2. `plumbline verify` against a report with one score improved by hand, which
   must refuse with exit 3;
3. `plumbline verify` against a report edited *and re-sealed*, which must still
   refuse with exit 3, because the run id it claims is not the one its contents
   generate;
4. the evidence tamper drill: plant a number the sources do not support, run
   the gate (integrity refusal, exit 3, nothing scored), re-seal, run it again
   (exit 1, the fabrication caught and scored).

Any of those coming back with a different exit code, or the clean run
producing a different run id, aborts the build. There is no path here that
publishes a page saying the harness refused when it did not.

    python3 tools/build_site.py            # writes site/index.html
    python3 tools/build_site.py --check    # rebuild and compare, do not write

`--check` is what CI runs before deploying, and what `tests/test_site.py` runs
on every test run: the committed page must be exactly what today's evidence
produces. A published report that has drifted from the committed one would be
a provenance claim nobody can back.

No network, no clock, no randomness: the page is a pure function of the
repository, which is the same property the reports themselves have.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SITE_DIR = REPO / "site"
PAGE = SITE_DIR / "index.html"

REPO_URL = "https://github.com/ChelseaKR/plumbline"

# Where these bytes are actually served. The trailing slash is part of it: the page is
# published under a PROJECT PATH on `chelseakr.github.io`, an origin this site shares with
# five other unrelated projects. `https://chelseakr.github.io/` is therefore not a shorter
# spelling of this site's root — it is a different address, it 404s, and every one of the six
# would claim it. Anything that names this page names the whole URL, path segment included.
PAGE_URL = "https://chelseakr.github.io/plumbline/"

# One title and one description, rendered into `<title>`/`og:title` and
# `<meta name="description">`/`og:description`. A second copy of a sentence is a second thing
# to keep true, and the copy that drifts is the one a search result or a chat preview shows
# instead of the page. Both restate what the page already says of itself and count nothing:
# every number on this page is produced by the build, and a figure pasted into a preview card
# is outside the reach of the freshness check that keeps the rest of it honest.
# The canonical carries an inline `nosemgrep`, and this is why.
#
# `html.security.audit.missing-integrity` fires on any `<link>` whose href has a scheme and
# no `integrity` attribute. It has no condition on `rel` at all, and it already carves out
# `rel="preconnect"` -- which is the identical case. A canonical URL is a metadata hint: the
# browser never fetches it, so there is no delivered file to hash and `integrity` has nothing
# to attach to. Adding one would not be a weaker fix, it would be meaningless markup.
#
# CI runs `semgrep ci --config auto` (.github/workflows/security.yml), which pulls the
# registry HTML rules, and the finding is blocking. Verified with
# `semgrep scan --config r/html.security.audit.missing-integrity`: 1 finding before, 0 after.
#
# Two details this cost a round trip to learn, so they are written down. The comment must sit
# on the SAME line as the tag: on the preceding line it is not honoured for this rule, and the
# scan still reported the finding. And the id must be the full, doubled
# `html.security.audit.missing-integrity.missing-integrity`; the shorter path prefix is not a
# match, and semgrep does not warn -- it simply does not suppress.
#
# It is a line-level suppression naming the one rule, not a `.semgrepignore` entry. That file
# says why in its own comment: it is for a file that CANNOT carry an inline comment because
# it is content-hashed. This page is generated, so the comment belongs in the generator and
# the regenerated page still matches its build-parity check. Ignoring `site/index.html`
# wholesale would blind semgrep to the entire published page to silence one false positive.
PAGE_TITLE = "Plumbline — audit evidence"
PAGE_DESCRIPTION = (
    "The committed audit report of the Plumbline evaluation harness, "
    "and the harness refusing to score tampered evidence."
)
BLANK_RESPONSE_FIX = "5caf8e5"


class DrillFailed(RuntimeError):
    """A drill did not behave the way the page is about to claim it does."""


# --- running the harness ----------------------------------------------------

def _run(args: list[str], cwd: Path) -> tuple[int, str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO / "src")
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    result = subprocess.run(
        [sys.executable, "-m", "plumbline", *args],
        cwd=cwd, env=env, capture_output=True, text=True,
    )
    return result.returncode, result.stdout, result.stderr


def _scratch_repo(root: Path) -> Path:
    """A minimal copy of the repository's evidence, at the same relative paths,
    so the documented command can be run verbatim inside it."""
    scratch = root / "scratch"
    (scratch / "examples").mkdir(parents=True)
    shutil.copytree(REPO / "datasets" / "riverbend-demo",
                    scratch / "datasets" / "riverbend-demo")
    shutil.copytree(REPO / "baselines", scratch / "baselines")
    shutil.copy(REPO / "examples" / "riverbend.toml",
                scratch / "examples" / "riverbend.toml")
    return scratch


def _expect(code: int, expected: int, what: str, output: str) -> None:
    if code != expected:
        raise DrillFailed(
            f"{what}: expected exit {expected}, got {code}.\n{output}")


def clean_run(scratch: Path, expected_run_id: str) -> dict:
    code, out, _ = _run(["gate", "--config", "examples/riverbend.toml",
                         "--out", "audits"], scratch)
    _expect(code, 0, "the documented gate command on untouched evidence", out)
    produced = sorted(p.name for p in (scratch / "audits").iterdir())
    if produced != [expected_run_id]:
        raise DrillFailed(
            f"the documented command produced {produced}, but the committed "
            f"report is {expected_run_id}. The page would be describing a run "
            f"this repository does not contain.")
    return {"code": code, "run_id": expected_run_id}


def seal_drill(scratch: Path, run_id: str) -> dict:
    """Two refusals over the same report: the seal, and the run id."""
    report_path = scratch / "audits" / run_id / "report.json"
    original = report_path.read_text(encoding="utf-8")
    report = json.loads(original)

    # 1. A score improved by hand, seal left alone.
    doctored = json.loads(original)
    suite = next(s for s in doctored["suites"] if s["suite"] == "accuracy")
    before = suite["score"]
    suite["score"] = 0.9638
    report_path.write_text(json.dumps(doctored, indent=2), encoding="utf-8")
    code, _, err = _run(["verify", f"audits/{run_id}/report.json"], scratch)
    _expect(code, 3, "verify against a hand-edited score", err)
    edited = {"code": code, "stderr": err.strip(), "before": before,
              "after": suite["score"]}

    # 2. The same edit, re-sealed the way a careful forger would: the target
    #    renamed, the seal recomputed over the change. The seal now matches.
    sys.path.insert(0, str(REPO / "src"))
    from plumbline.report import seal_report  # noqa: PLC0415  (local by design)

    forged = json.loads(original)
    forged["target"] = "some-other-system"
    forged["provenance"].pop("report_sha256", None)
    seal_report(forged)
    report_path.write_text(json.dumps(forged, indent=2), encoding="utf-8")
    code, _, err = _run(["verify", f"audits/{run_id}/report.json"], scratch)
    _expect(code, 3, "verify against a re-sealed forgery", err)
    resealed = {"code": code, "stderr": err.strip()}

    report_path.write_text(original, encoding="utf-8")
    return {"edited": edited, "resealed": resealed,
            "seal": report["provenance"]["report_sha256"]}


def evidence_drill(scratch: Path) -> dict:
    """The tamper drill from the README, executed."""
    bundle = scratch / "datasets" / "riverbend-demo"
    responses = bundle / "responses.jsonl"
    before_hash = json.loads(
        (bundle / "checksums.json").read_text(encoding="utf-8"))["bundle_sha256"]

    responses.write_text(
        responses.read_text(encoding="utf-8").replace("850 dollars",
                                                      "900 dollars"),
        encoding="utf-8")

    code, out, err = _run(["gate", "--config", "examples/riverbend.toml",
                           "--out", "tamper"], scratch)
    _expect(code, 3, "the gate over edited, unsealed evidence", err or out)
    refusal = err.strip().splitlines()[0]
    wrote_nothing = not (scratch / "tamper").exists()

    _expect(_run(["seal", "datasets/riverbend-demo"], scratch)[0], 0,
            "re-sealing the edited bundle", "")
    after_hash = json.loads(
        (bundle / "checksums.json").read_text(encoding="utf-8"))["bundle_sha256"]

    code, out, _ = _run(["gate", "--config", "examples/riverbend.toml",
                         "--out", "tamper"], scratch)
    _expect(code, 1, "the gate over re-sealed, fabricated evidence", out)
    # Only the block the gate prints under its "N of M suites failed:" header.
    # A looser pattern picks up the baseline block's `REFUSED:` and `flipped:`
    # lines further down, and a page that called those suites would be wrong
    # about the one thing it is there to show.
    failed = []
    lines = out.splitlines()
    for i, line in enumerate(lines):
        if re.match(r"^\d+ of \d+ suites failed:$", line):
            for tail in lines[i + 1:]:
                match = re.match(r"^  (\w+): (.+)$", tail)
                if not match:
                    break
                failed.append((match.group(1), match.group(2)))
            break
    if not failed:
        raise DrillFailed(f"no failing suites named in:\n{out}")
    return {
        "refusal": refusal,
        "wrote_nothing": wrote_nothing,
        "before": before_hash[:12],
        "after": after_hash[:12],
        "failed": failed,
    }


# --- collecting -------------------------------------------------------------

def committed() -> dict:
    reports = sorted((REPO / "audits").glob("*/report.json"))
    if len(reports) != 1:
        raise DrillFailed(
            f"expected exactly one committed audit, found {len(reports)}")
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    matrix = json.loads(
        (REPO / "proof" / "matrix.json").read_text(encoding="utf-8"))
    return {"report": report, "matrix": matrix,
            "report_path": reports[0].relative_to(REPO).as_posix()}


def collect() -> dict:
    data = committed()
    run_id = data["report"]["provenance"]["run_id"]
    with tempfile.TemporaryDirectory() as tmp:
        scratch = _scratch_repo(Path(tmp))
        data["clean"] = clean_run(scratch, run_id)
        data["seal_drill"] = seal_drill(scratch, run_id)
        data["evidence_drill"] = evidence_drill(scratch)
    return data


# --- rendering --------------------------------------------------------------

CSS = """
:root {
  color-scheme: light dark;
  --bg: #fbfaf8; --fg: #1b1a18; --muted: #5d5a55; --rule: #dedad2;
  --card: #ffffff; --accent: #7a2e12; --ok: #1f5d3a; --stop: #8f2119;
  --code-bg: #f2efe9;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #17171a; --fg: #e9e7e3; --muted: #a6a29b; --rule: #33322f;
    --card: #1f1f23; --accent: #e8a07a; --ok: #7fc79c; --stop: #f08a80;
    --code-bg: #26262a;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--fg);
  font: 16px/1.6 ui-serif, Georgia, "Iowan Old Style", serif;
  -webkit-text-size-adjust: 100%;
}
main { max-width: 46rem; margin: 0 auto; padding: 3rem 1.25rem 5rem; }
h1 { font-size: 2rem; line-height: 1.15; margin: 0 0 .4rem; letter-spacing: -.01em; }
h2 { font-size: 1.3rem; margin: 3rem 0 .75rem; letter-spacing: -.01em; }
h3 { font-size: 1.02rem; margin: 2rem 0 .5rem; }
p, li { color: var(--fg); }
.lede { font-size: 1.1rem; color: var(--muted); margin: 0 0 2rem; }
a { color: var(--accent); text-decoration-thickness: 1px; text-underline-offset: 2px; }
code, pre, .mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: .86em;
}
code { background: var(--code-bg); padding: .1em .3em; border-radius: 3px; }
pre {
  background: var(--code-bg); padding: 1rem; border-radius: 6px;
  overflow-x: auto; line-height: 1.5; border: 1px solid var(--rule);
}
pre code { background: none; padding: 0; }
.note {
  border-left: 3px solid var(--rule); padding: .1rem 0 .1rem 1rem;
  color: var(--muted); margin: 1.5rem 0;
}
.card {
  background: var(--card); border: 1px solid var(--rule); border-radius: 8px;
  padding: 1.1rem 1.25rem; margin: 1.5rem 0;
}
.kv { margin: 0; display: grid; grid-template-columns: max-content 1fr; gap: .35rem 1rem; }
.kv dt { color: var(--muted); font-size: .9rem; }
.kv dd { margin: 0; word-break: break-all; }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: .92rem; }
th, td { text-align: left; padding: .4rem .6rem; border-bottom: 1px solid var(--rule); white-space: nowrap; }
th { color: var(--muted); font-weight: 600; font-size: .82rem; text-transform: uppercase; letter-spacing: .04em; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
.pass { color: var(--ok); font-weight: 600; }
.stop { color: var(--stop); font-weight: 600; }
.exit { display: inline-block; padding: .05em .45em; border-radius: 4px;
        background: var(--code-bg); border: 1px solid var(--rule); }
footer { margin-top: 4rem; padding-top: 1.5rem; border-top: 1px solid var(--rule);
         color: var(--muted); font-size: .9rem; }
"""


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def suite_rows(report: dict) -> str:
    rows = []
    for s in report["suites"]:
        ci = ("n/a" if s["ci"] is None
              else f"{s['ci']['lower']:.3f}–{s['ci']['upper']:.3f}")
        mde = "n/a" if s["mde"] is None else f"{s['mde']:.3f}"
        klass = "pass" if s["verdict"] == "PASS" else "stop"
        rows.append(
            f"<tr><td><code>{esc(s['suite'])}</code></td>"
            f"<td class=\"num\">{s['score']:.4f}</td>"
            f"<td class=\"num\">{s['floor']:.2f}</td>"
            f"<td class=\"{klass}\">{esc(s['verdict'])}</td>"
            f"<td class=\"num\">{s['n']}</td>"
            f"<td class=\"num\">{ci}</td>"
            f"<td class=\"num\">{mde}</td></tr>")
    return "\n".join(rows)


def coverage_lines(report: dict) -> str:
    lines = []
    for s in report["suites"]:
        block = (s.get("details") or {}).get("unverifiable")
        if not block or not block.get("count"):
            continue
        reasons = ", ".join(f"{reason} {len(ids)}"
                            for reason, ids in block["reasons"].items())
        lines.append(
            f"<li><code>{esc(s['suite'])}</code> scored "
            f"<strong>{block['scored']} of {block['eligible']}</strong> "
            f"eligible items. {block['count']} are UNVERIFIABLE "
            f"({esc(reasons)}) — excluded from the score, and not counted as "
            f"passes.</li>")
    return "\n".join(lines)


def render(data: dict) -> str:
    report = data["report"]
    p = report["provenance"]
    matrix = data["matrix"]
    seal = data["seal_drill"]
    drill = data["evidence_drill"]
    run_id = esc(p["run_id"])
    failed_suites = "\n".join(
        f"<li><code>{esc(name)}</code>: {esc(reason)}</li>"
        for name, reason in drill["failed"])

    drill_before = f"{seal['edited']['before']:.4f}"
    drill_after = f"{seal['edited']['after']:.4f}"
    edited_stderr = esc(seal["edited"]["stderr"])
    edited_code = seal["edited"]["code"]
    resealed_stderr = esc(seal["resealed"]["stderr"])
    resealed_code = seal["resealed"]["code"]
    tamper_refusal = esc(drill["refusal"])
    wrote_nothing = ("no report was written" if drill["wrote_nothing"]
                     else "nothing was scored")
    before_hash = esc(drill["before"])
    after_hash = esc(drill["after"])
    items = report["dataset"]["items"]
    repo = REPO_URL
    repo_label = REPO_URL.replace("https://", "")
    fix = BLANK_RESPONSE_FIX
    report_path = esc(data["report_path"])
    verdict = esc(report["verdict"])
    target = esc(report["target"])
    harness_version = esc(p["harness_version"])
    harness_source = esc(p["harness_source_sha256"][:12])
    dataset_sha = esc(p["dataset_id"])
    judge_kind = esc(p["judge_kind"])
    judge_hash = esc(p["judge_config_sha256"][:12])
    report_seal = esc(p["report_sha256"][:12])
    seed = esc(p["seed"])
    rows = suite_rows(report)
    coverage = coverage_lines(report)
    suite_count = len(report["suites"])
    cases_held = sum(1 for c in matrix["cases"] if c["held"])
    cases_total = len(matrix["cases"])

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{PAGE_TITLE}</title>
<meta name="description" content="{PAGE_DESCRIPTION}">
<link rel="canonical" href="{PAGE_URL}"> <!-- nosemgrep: html.security.audit.missing-integrity.missing-integrity -->
<meta property="og:type" content="website">
<meta property="og:site_name" content="Plumbline">
<meta property="og:title" content="{PAGE_TITLE}">
<meta property="og:description" content="{PAGE_DESCRIPTION}">
<meta property="og:url" content="{PAGE_URL}">
<meta property="og:locale" content="en_US">
<meta name="twitter:card" content="summary">
<style>{CSS}</style>
</head>
<body>
<main>

<h1>Plumbline</h1>
<p class="lede">A fail-closed evaluation harness for government-facing chat
systems. This page is not a description of it: every exit code and transcript
below was produced by running it, and the page cannot be built if any of them
comes back different.</p>

<h2>It refuses</h2>

<p>The most useful thing an audit harness can do is decline to produce a
verdict. Three refusals, run against this repository's own committed
evidence when this page was built.</p>

<h3>1. A report edited after it was written</h3>

<p>One score improved by hand — <code>accuracy</code>
{drill_before} → {drill_after} — and nothing else touched:</p>

<pre><code>$ plumbline verify audits/{run_id}/report.json
{edited_stderr}</code></pre>

<p>Exit <span class="exit">{edited_code}</span>: integrity refusal.</p>

<h3>2. The same edit, re-sealed</h3>

<p>The seal is a plain SHA-256 with no secret in it, so an editor can
recompute it. Here the target name is changed and the seal is recomputed over
the change — the seal now matches the contents perfectly:</p>

<pre><code>$ plumbline verify audits/{run_id}/report.json
{resealed_stderr}</code></pre>

<p>Exit <span class="exit">{resealed_code}</span>. The run id is a hash of the
run's inputs, and every one of them is written in the report, so the report
must generate the identity it claims. This is <strong>tamper evidence, not
authentication</strong>: it establishes that the copy in front of you is the
copy that was written. Vouching for <em>who</em> produced a report needs a
signature over these bytes, and Plumbline does not issue one.</p>

<h3>3. Evidence edited underneath the harness</h3>

<p>A number the sources do not support, planted in the recorded responses:</p>

<pre><code>$ plumbline gate --config examples/riverbend.toml --out tamper
{tamper_refusal}</code></pre>

<p>Exit <span class="exit">3</span>, and {wrote_nothing}. Re-sealing the bundle
makes it runnable again and changes the dataset hash
(<code>{before_hash}</code> → <code>{after_hash}</code>) — that trace is the
point. The second run scores the fabrication instead of refusing it, exit
<span class="exit">1</span>, with these suites failing:</p>

<ul>
{failed_suites}
</ul>

<p>Across {items} items the planted number barely moves a pooled average. The
suites fail on the load-bearing severity rule instead, which is the argument
for having one.</p>

<h2>It has reported a false pass, twice</h2>

<p>A target returning <strong>174 empty responses scored a perfect 1.0000 on
five suites</strong> — <code>groundedness</code>, <code>privacy</code>,
<code>representational_harms</code>, <code>fairness</code> and
<code>cross_language</code> — and the gate returned PASS, exit 0. Silence
satisfies every check phrased as the absence of something bad. That was fixed
in <a href="{repo}/commit/{fix}"><code>{fix}</code></a>.</p>

<p>The fix tested <code>response.strip()</code>. A target answering every item
with <code>"."</code> scored the identical 1.0000 on the identical five suites
until the next pass, as did a target that answered a third of the corpus and
went quiet for the rest — every suite excluded the silence and no suite counted
it. Both are now pinned by tests that fail without the fix.</p>

<p class="note">Published because an evaluation harness that has never reported
a false pass has probably not been looked at hard enough, and because anyone
deciding whether to trust this one should be able to read how it has been
wrong.</p>

<h2>The committed verdict</h2>

<p>Reproduced from a clean copy while this page was built: the documented
command wrote run <code>{run_id}</code>, byte for byte the report committed at
<a href="{repo}/blob/main/{report_path}"><code>{report_path}</code></a>.</p>

<div class="card">
<dl class="kv">
<dt>Verdict</dt><dd class="pass">{verdict}</dd>
<dt>Target</dt><dd><code>{target}</code></dd>
<dt>Run id</dt><dd><code>{run_id}</code></dd>
<dt>Harness</dt><dd><code>{harness_version}</code>, source
  <code>{harness_source}</code></dd>
<dt>Dataset</dt><dd><code>{dataset_sha}</code> ({items} items)</dd>
<dt>Judge</dt><dd><code>{judge_kind}</code>, config
  <code>{judge_hash}</code></dd>
<dt>Report seal</dt><dd><code>{report_seal}</code></dd>
<dt>Seed</dt><dd><code>{seed}</code></dd>
</dl>
</div>

<div class="scroll">
<table>
<thead><tr><th>Suite</th><th>Score</th><th>Floor</th><th>Verdict</th>
<th>n</th><th>95% CI</th><th>MDE</th></tr></thead>
<tbody>
{rows}
</tbody>
</table>
</div>

<p>MDE is the smallest true drop a same-sized future run could tell apart from
noise. A suite can sit well above its floor and still be unable to catch a
regression anyone would care about; printing it next to the score makes that
visible rather than leaving it for the reader to work out.</p>

<ul>
{coverage}
</ul>

<p class="note"><strong>The dataset is a demonstration, not a benchmark.</strong>
Everything under <code>datasets/</code> is synthetic and written for this
repository — a fictional county, fictional programs, fictional numbers,
generated by a committed script. No score here says anything about any real
system. The harness is the product.</p>

<h2>Every suite has been observed failing</h2>

<p>A suite that has never failed is indistinguishable from a suite that
<em>cannot</em> fail. For each of the {suite_count} suites, the
defect-injection matrix plants a defect that suite exists to catch, runs the
real audit path end to end, and checks both that the suite fails and that the
suites which should be indifferent stay passing:
<strong>{cases_held} of {cases_total} cases held</strong>
(<a href="{repo}/blob/main/proof/matrix.md">proof/matrix.md</a>).</p>

<footer>
<p>Source, and everything above as files you can check yourself:
<a href="{repo}">{repo_label}</a>. Apache-2.0. This page is generated by
<code>tools/build_site.py</code> from the committed artifacts and rebuilt on
every run of the test suite; if it disagreed with them by one byte, the build
would fail rather than publish.</p>
</footer>

</main>
</body>
</html>
"""


def build() -> str:
    return render(collect())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the published evidence page from committed "
                    "artifacts, by running them.")
    parser.add_argument("--check", action="store_true",
                        help="rebuild and compare against the committed page; "
                             "do not write")
    args = parser.parse_args(argv)

    try:
        page = build()
    except DrillFailed as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        print("The page would have claimed something the harness did not do.",
              file=sys.stderr)
        return 1

    if args.check:
        current = PAGE.read_text(encoding="utf-8") if PAGE.is_file() else None
        if current != page:
            print(f"{PAGE.relative_to(REPO)} is not what the committed "
                  f"evidence produces; run `python3 tools/build_site.py`",
                  file=sys.stderr)
            return 1
        print(f"{PAGE.relative_to(REPO)} is current")
        return 0

    SITE_DIR.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(page, encoding="utf-8")
    print(f"wrote: {PAGE.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
