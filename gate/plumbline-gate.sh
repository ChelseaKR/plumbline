#!/bin/sh
#
# Plumbline gate runner. Copy this one file into a repository you want gated,
# next to a plumbline.pin file, and both a developer's laptop and CI run the
# identical command against the identical pinned harness.
#
# What it does:
#   1. Reads plumbline.pin: which harness, which exact commit, which target
#      config, and optionally which baseline.
#   2. Resolves that commit into a cache directory at run time. The harness is
#      never a package dependency of the repository being gated.
#   3. Verifies the resolved checkout is at the pinned commit.
#   4. Runs `plumbline gate` and exits with its exit code.
#
# Every failure to do any of that exits 4 with a reason on stderr. There is no
# path through this script that skips the gate or reports success without
# having run it: a gate that could not run is not a gate that passed.
#
# Exit codes (identical to the harness's own):
#   0  all enabled suites passed
#   1  at least one suite failed
#   2  usage error
#   3  integrity refusal: the evidence bundle did not verify, nothing scored
#   4  configuration or environment error, including "the harness could not
#      be resolved"
#   5  internal error: the harness itself crashed. Distinct from 1 because
#      exit 1 is a measurement and a crash is the absence of one.
#
# Every non-zero code blocks. None of them means "could not check, carry on".
#
# Environment overrides:
#   PLUMBLINE_PIN_FILE   pin file to read           (default: plumbline.pin)
#   PLUMBLINE_CACHE_DIR  where resolved harnesses live (default: .plumbline-cache)
#   PLUMBLINE_PYTHON     interpreter                (default: python3)
#   PLUMBLINE_SRC        bypass resolution and use this src/ directory.
#                        For developing the harness itself. Loud on purpose.
#                        CI must never set it.

set -eu

passthrough_count=$#

EXIT_ENVIRONMENT=4

fail() {
    printf 'PLUMBLINE GATE: %s\n' "$1" >&2
    printf 'PLUMBLINE GATE: FAILED before scoring. A gate that cannot run is not a gate that passed.\n' >&2
    exit "$EXIT_ENVIRONMENT"
}

PIN_FILE="${PLUMBLINE_PIN_FILE:-plumbline.pin}"
if [ ! -f "$PIN_FILE" ]; then
    fail "no pin file at '$PIN_FILE'. The pin file is the single place this repository records which harness commit gates it; without it there is nothing to run."
fi

pin_repo=''
pin_ref=''
pin_config=''
pin_baseline=''
pin_out='plumbline-audits'
pin_require_comparable='false'

while IFS= read -r line || [ -n "$line" ]; do
    line=${line%%#*}
    case "$line" in
        *=*) ;;
        *) continue ;;
    esac
    key=$(printf '%s' "${line%%=*}" | tr -d ' \t')
    value=$(printf '%s' "${line#*=}" | sed 's/^[ 	]*//; s/[ 	]*$//')
    case "$key" in
        repo) pin_repo=$value ;;
        ref) pin_ref=$value ;;
        config) pin_config=$value ;;
        baseline) pin_baseline=$value ;;
        out) pin_out=$value ;;
        require_comparable_baseline) pin_require_comparable=$value ;;
        '') ;;
        *) fail "unknown key '$key' in $PIN_FILE (known keys: repo, ref, config, baseline, out, require_comparable_baseline)" ;;
    esac
done < "$PIN_FILE"

if [ -z "$pin_config" ]; then
    fail "$PIN_FILE does not set 'config', so there is no target to audit"
fi

if [ -n "${PLUMBLINE_SRC:-}" ]; then
    printf 'PLUMBLINE GATE: PLUMBLINE_SRC is set, so the pin in %s was BYPASSED.\n' "$PIN_FILE" >&2
    printf 'PLUMBLINE GATE: this run is NOT pinned and its result is not reproducible from %s. CI must not set PLUMBLINE_SRC.\n' "$PIN_FILE" >&2
    harness_src="$PLUMBLINE_SRC"
else
    if [ -z "$pin_repo" ]; then
        fail "$PIN_FILE does not set 'repo'"
    fi
    if [ -z "$pin_ref" ]; then
        fail "$PIN_FILE does not set 'ref'"
    fi
    if [ "${#pin_ref}" -ne 40 ] || [ -n "$(printf '%s' "$pin_ref" | tr -d '0123456789abcdef')" ]; then
        fail "ref '$pin_ref' is not a 40-character commit hash. Pin an exact commit: a branch or tag can move under you, and then a green gate means nothing."
    fi
    if ! command -v git >/dev/null 2>&1; then
        fail "git is not available, so the pinned harness cannot be resolved"
    fi

    cache_root="${PLUMBLINE_CACHE_DIR:-.plumbline-cache}"
    cache="$cache_root/$pin_ref"

    if [ ! -d "$cache/.git" ]; then
        rm -rf "$cache"
        mkdir -p "$cache" || fail "cannot create the harness cache directory '$cache'"
        git init --quiet "$cache" || fail "git init failed in '$cache'"
        git -C "$cache" remote add origin "$pin_repo" \
            || fail "cannot configure remote '$pin_repo'"
        if ! git -C "$cache" fetch --quiet --depth 1 origin "$pin_ref" 2>/dev/null; then
            git -C "$cache" fetch --quiet origin 2>/dev/null \
                || fail "cannot reach the pinned harness at '$pin_repo' (commit $pin_ref). Check network access and the repository URL. The gate fails rather than skipping."
        fi
        git -C "$cache" checkout --quiet "$pin_ref" 2>/dev/null \
            || git -C "$cache" checkout --quiet FETCH_HEAD 2>/dev/null \
            || fail "commit $pin_ref is not present in '$pin_repo'"
    fi

    resolved=$(git -C "$cache" rev-parse HEAD 2>/dev/null) \
        || fail "cannot read the resolved harness checkout in '$cache'"
    if [ "$resolved" != "$pin_ref" ]; then
        fail "the resolved harness is at commit $resolved but $PIN_FILE pins $pin_ref. Delete '$cache' and retry."
    fi
    harness_src="$cache/src"
fi

if [ ! -d "$harness_src" ]; then
    fail "the resolved harness has no src/ directory at '$harness_src'"
fi

PLUMBLINE_PYTHON="${PLUMBLINE_PYTHON:-python3}"
if ! command -v "$PLUMBLINE_PYTHON" >/dev/null 2>&1; then
    fail "'$PLUMBLINE_PYTHON' is not available; set PLUMBLINE_PYTHON to an interpreter of Python 3.11 or newer"
fi

# Build the harness command line after this script's own arguments, then
# rotate this script's arguments to the end so they are passed through (for
# example: plumbline-gate.sh --summary-file "$GITHUB_STEP_SUMMARY").
set -- "$@" gate --config "$pin_config" --out "$pin_out"
if [ -n "$pin_baseline" ]; then
    set -- "$@" --baseline "$pin_baseline"
fi
if [ "$pin_require_comparable" = "true" ]; then
    set -- "$@" --require-comparable-baseline
fi
rotated=0
while [ "$rotated" -lt "$passthrough_count" ]; do
    head_arg=$1
    shift
    set -- "$@" "$head_arg"
    rotated=$((rotated + 1))
done

exec env PYTHONPATH="$harness_src${PYTHONPATH:+:$PYTHONPATH}" \
    "$PLUMBLINE_PYTHON" -m plumbline "$@"
