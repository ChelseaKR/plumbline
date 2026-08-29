# The local gate. `make verify` runs the checks a contributor can run offline,
# with no key and no network, and every one of them can fail.
#
# It now also runs the byte-for-byte reproduction of the committed audit and
# the tamper drill. Those two used to be deliberately excluded, on the grounds
# that both mutate the working tree -- `audits/` and `datasets/riverbend-demo`
# -- and that a gate people learn to run `git checkout --` after is a gate
# people learn to ignore. The reasoning was right about the symptom and wrong
# about the cure: the consequence was that `make verify` passed on trees
# `.github/workflows/tests.yml` rejects, which is the shape this repository
# exists to argue against. Neither check needs to mutate anything:
# `reproduce` writes into a temporary directory and compares, and
# `tamper-drill` tampers with a copy. The checkout stays clean and the local
# gate now covers the workflow.
#
# `tests/test_ci_parity.py` holds that open: every `run:` step in tests.yml
# must be a make target, and `verify` must reach it.

.PHONY: verify lint test test-bare coverage site-check claims-check clean reproduce tamper-drill sast

verify: lint test site-check claims-check reproduce tamper-drill
	@echo "make verify: all local gates passed."

# Ruff's default rules. The narrow select set is a recorded gap, not an
# oversight; see the comment in pyproject.toml and the README's conformance
# table for the measured counts. `ruff format --check` is deliberately not
# wired: it would reformat 54 of this repository's 59 Python files, and a
# whole-tree reformat is a decision to take on its own, not a side effect of
# turning a linter on.
#
# mypy checks `src/plumbline` only, at `--strict` (see `[tool.mypy]` in
# pyproject.toml for why that setting and not something narrower). `tests`
# and `tools` are not type-checked: `tests` uses `unittest`'s own dynamic
# patterns throughout, and neither is shipped.
lint:
	uv run ruff check src tests tools
	uv run mypy

# The suite runs on the standard library alone, exactly as CI runs it. Coverage
# only wraps it; it does not change what is executed. The floor is in
# pyproject.toml and `coverage report` exits non-zero below it.
test:
	PYTHONPATH=src:tests uv run coverage run -m unittest discover -s tests
	uv run coverage report

# The same suite on a bare interpreter, with nothing installed and no uv. This
# is the property the version matrix in .github/workflows/tests.yml exists to
# hold: that Plumbline runs on the standard library alone. `make` is not a
# Python package, so calling the suite through a target does not spend it.
test-bare:
	PYTHONPATH=src:tests python3 -m unittest discover -s tests

# The published evidence page has to be what the committed evidence produces,
# and it has to hold up to the same accessibility standard it holds a
# target's interface to. Same checks `.github/workflows/pages.yml` runs
# before it deploys anything.
site-check:
	PYTHONPATH=src uv run python3 tools/build_site.py --check
	PYTHONPATH=src uv run python3 tools/check_site_a11y.py

# The same standard, applied to the prose. `site-check` above regenerates the
# published page and compares it byte for byte, so the page cannot drift; the
# README and DESIGN.md had nothing holding them to the same artifacts, and
# they drifted -- four figures describing a 174-item demo bundle that has held
# 178 since the multi-turn items landed. This checks the numbers rather than
# regenerating the documents: a tool that owned every byte of the README would
# own the argument in it too.
claims-check:
	PYTHONPATH=src uv run python3 tools/check_claims.py

clean:
	rm -rf .coverage htmlcov .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

# ----------------------------------------------------------------------------
# The gates that used to run only in CI.
# ----------------------------------------------------------------------------

# A scratch tree these targets are allowed to dirty. Never the checkout.
WORKDIR ?= .make-work

# The committed audit of the bundled demo must be what this code produces.
#
# The run is written to a temporary directory and compared, rather than over
# `audits/` and then inspected with git. `diff -r` is the comparison because it
# fails on three things a content diff of tracked files alone would not: a
# changed byte, a report the run no longer writes, and a directory the run
# writes that is not committed. A moved run id produces the third -- the run id
# is the directory's name, so a run that moves it leaves the committed
# directory untouched and writes a new one beside it.
reproduce:
	rm -rf $(WORKDIR)/reproduce && mkdir -p $(WORKDIR)/reproduce
	PYTHONPATH=src python3 -m plumbline gate \
	  --config examples/riverbend.toml --out $(WORKDIR)/reproduce
	@test -n "$$(ls -A audits)" || { echo "audits/ is empty; there is nothing to reproduce and this check would pass over nothing" >&2; exit 1; }
	diff -r audits $(WORKDIR)/reproduce
	# The committed report must also still match its own seal.
	PYTHONPATH=src python3 -m plumbline verify audits/*/report.json
	@echo "reproduce: the committed audit is byte-for-byte what this code produces"

# The tamper drill from the README, against a copy of the checkout.
#
# Exit codes are captured explicitly rather than leaned on through `&&`: a
# drill asserting only "did not exit 0" is satisfied by the harness crashing,
# which is the opposite of what it proves. 3 is the integrity refusal; 1 is the
# re-sealed bundle's fabrication being caught and scored.
tamper-drill:
	rm -rf $(WORKDIR)/drill && mkdir -p $(WORKDIR)/drill
	git ls-files -co --exclude-standard -z | rsync -a --files-from=- --from0 . $(WORKDIR)/drill/
	@test -f $(WORKDIR)/drill/datasets/riverbend-demo/responses.jsonl || { echo "the copy has no dataset; the drill would prove nothing" >&2; exit 1; }
	@set -eu; cd $(WORKDIR)/drill; \
	  python3 -c "import pathlib; p=pathlib.Path('datasets/riverbend-demo/responses.jsonl'); p.write_text(p.read_text().replace('850 dollars','900 dollars'))"; \
	  set +e; PYTHONPATH=src python3 -m plumbline gate --config examples/riverbend.toml --out out1 >/dev/null 2>&1; code=$$?; set -e; \
	  [ "$$code" = "3" ] || { echo "expected exit 3 (integrity refusal), got $$code" >&2; exit 1; }; \
	  PYTHONPATH=src python3 -m plumbline seal datasets/riverbend-demo >/dev/null; \
	  set +e; PYTHONPATH=src python3 -m plumbline gate --config examples/riverbend.toml --out out2 >/dev/null 2>&1; code=$$?; set -e; \
	  [ "$$code" = "1" ] || { echo "expected exit 1 (the fabrication is caught and scored), got $$code" >&2; exit 1; }; \
	  echo "tamper-drill: integrity refusal (3), then the fabrication caught and scored (1)"

# Static analysis a contributor can run. CI runs semgrep too, in the pinned
# container in .github/workflows/security.yml, with `semgrep ci`; this is the
# same ruleset through the CLI, so it is a local approximation rather than a
# reproduction, and `tests/test_ci_parity.py` scopes itself to tests.yml for
# exactly that reason.
SEMGREP_VERSION ?= 1.168.0
sast:
	uvx --from semgrep==$(SEMGREP_VERSION) semgrep scan --error --metrics off --config auto .
