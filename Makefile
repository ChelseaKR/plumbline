# The local gate. `make verify` runs the checks a contributor can run offline,
# with no key and no network, and every one of them can fail.
#
# What is deliberately NOT here: the tamper drill and the byte-for-byte
# reproduction of the committed audit. Both mutate the working tree
# (`datasets/riverbend-demo` and `audits/`) and both already run in
# `.github/workflows/tests.yml`, where the tree is disposable. Running them
# from a target a contributor invokes casually would leave that contributor's
# checkout dirty, and a gate people learn to run with `git checkout --` after
# it is a gate people learn to ignore.

.PHONY: verify lint test coverage site-check clean

verify: lint test site-check
	@echo "make verify: all local gates passed."

# Ruff's default rules. The narrow select set is a recorded gap, not an
# oversight; see the comment in pyproject.toml and the README's conformance
# table for the measured counts. `ruff format --check` is deliberately not
# wired: it would reformat 54 of this repository's 59 Python files, and a
# whole-tree reformat is a decision to take on its own, not a side effect of
# turning a linter on.
#
# mypy checks `src/plumbline` only, at the default (non-strict) setting; see
# the comment in `[tool.mypy]` in pyproject.toml for the recorded gap between
# that and `--strict`. `tests` and `tools` are not type-checked: `tests` uses
# `unittest`'s own dynamic patterns throughout, and neither is shipped.
lint:
	uv run ruff check src tests tools
	uv run mypy

# The suite runs on the standard library alone, exactly as CI runs it. Coverage
# only wraps it; it does not change what is executed. The floor is in
# pyproject.toml and `coverage report` exits non-zero below it.
test:
	PYTHONPATH=src:tests uv run coverage run -m unittest discover -s tests
	uv run coverage report

# The published evidence page has to be what the committed evidence produces.
# Same check `.github/workflows/pages.yml` runs before it deploys anything.
site-check:
	PYTHONPATH=src uv run python3 tools/build_site.py --check

clean:
	rm -rf .coverage htmlcov .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
