# Observed failing, or it is not a gate

A suite that has never been observed failing is indistinguishable from a suite
that *cannot* fail, and a wall of green ticks proves nothing about which one you
have. This page is the procedure Plumbline uses to tell them apart, and — more
useful — the six distinct ways that procedure has lied, each caught, each with a
line of real code to look at.

It is written to be adopted. Nothing in it needs Plumbline; it needs a test
suite, `git`, and a willingness to treat the first run as the measurement.

## The claim

> A check is not trusted until it has been observed failing on a defect it
> exists to catch.

Coverage does not establish this. Coverage says a line ran. It says nothing
about whether anything would have failed had the line been wrong — a suite that
imports every module and asserts almost nothing reports the same number as a
suite that pins every boundary. That distinction is the whole subject here.

Plumbline already ships the artifact form of this claim:
[`tools/defect_matrix.py`](../tools/defect_matrix.py) plants, for each suite, a
defect that suite exists to catch, runs the real audit path end to end over the
real demonstration bundle, and writes [`proof/matrix.md`](../proof/matrix.md).
The committed matrix currently records **23 of 23 cases behaving as declared**,
covering **all 15 enabled suites**, with the note that matters: *"There is no
suite in this configuration whose failure path is untested."*

Three things about that file are worth copying before anything else:

- **It asserts twice per row.** The suite under test must fail, *and* the suites
  that should be indifferent must keep passing. Without the second assertion a
  sabotage crude enough to trip everything reads as a clean row. Collateral
  failures a case knows about are **declared with a reason** and printed as
  couplings; undeclared collateral fails the run.
- **It mutates the evidence, not the harness.** Every planted defect is an edit
  to what the target is recorded as having said. The defects arrive through the
  front door, the way a real one would.
- **It runs an unsabotaged control first, and asserts it passes.** Without that,
  every suite would "fail on its defect" because every suite was already
  failing, and the matrix would be a wall of green rows meaning nothing. The
  assertion is one line in
  [`tests/test_defect_matrix.py`](../tests/test_defect_matrix.py), and the
  comment above it is the reason this page exists. The same file also plants a
  case declaring the *wrong* suite, to establish that a row which stops holding
  is reported rather than absorbed — a control on the control.

## The procedure

Use git objects as the baseline. Not a copy in a scratch directory — a scratch
directory does not survive a restart, and a byte-copy comparison is one more
thing to get wrong.

```sh
# 0. Commit first. A committed baseline survives a process death; a copy does not.
git add path/to/file.py && git commit -m "baseline before control"

# 1. Take the baseline as an object hash.
git hash-object path/to/file.py            # -> BASE

# 2. Apply the sabotage, then PROVE it landed.
git hash-object path/to/file.py            # -> must NOT equal BASE

# 3. Run the suite. Confirm it goes red on exactly the tests you expect,
#    and that the tests you expect to be indifferent stay green.

# 4. Clear stale bytecode before you trust anything about the restore.
find . -name __pycache__ -type d -prune -exec rm -rf {} +

# 5. Restore, and assert the hash matches BASE exactly.
git checkout -- path/to/file.py
git hash-object path/to/file.py            # -> must equal BASE
```

Step 2 is the one people skip and the one that earns its keep. A sabotage that
silently does nothing produces a green run that reads exactly like a passing
guard. The hash assertion makes that impossible to mistake.

Two rules that go with the procedure:

- **Sabotage a literal, never a named constant.** Renaming a constant can fail
  loudly at import, which is a different signal from the one you are asking for.
- **If the control does not go red on its first run, that first run is the
  honest measurement.** Say so where the work is reviewed. Do not quietly
  retarget it and report a clean sweep.

## Six ways a control lies

### 1. The sabotage silently does not apply

A `perl -pi -e 's/old/new/'` whose pattern does not match exits `0` and changes
nothing. The suite then runs green over untouched code, and — with no baseline
assertion — that green run gets written down as a verified guard. This has
happened here, and only the hash comparison caught it.

The structural fix is to make the mutation itself raise. Plumbline's evidence
editor does exactly that:
[`tools/defect_matrix.py`](../tools/defect_matrix.py)'s `edit_response` raises
`KeyError` when the text it was told to replace is not in the recorded response,
and `set_response` resolves the item id first with the comment `raise early on a
typo'd id`. A mutation helper that can no-op is a control that can lie.

### 2. The branch you edited is unreachable from the fixture

Sabotaging a rule can leave a suite green because no test ever makes that rule's
condition arise — the code is executed, the branch is not.

The clean example is in a sibling project.
[`swelter`](https://github.com/ChelseaKR/swelter)'s reproduction verdict was
sabotaged and the suite stayed green, because no test made a required check fail
to *run*. The remedy was not a better sabotage; it was making the branch
reachable. `verdict_for()` was extracted for that reason and says so in its own
docstring:

> Separated from `reproduce` so the did-not-run branch is reachable from a test
> rather than being decoration that no case exercises.

Writing the test that reaches it then found a second defect: a `NOT_APPLICABLE`
required check was reading as a pass.

### 3. An earlier branch returns before your edit is read

A guard added ahead of the line you sabotaged, a short-circuit, a cached result:
the run never reaches the code you changed. This looks identical to case 2 from
the outside and has a different fix — find the caller path, not the fixture.

When a branch turns out to be unreachable *in effect* rather than merely
untested, label it. A dead branch left in place looks like a tested guard to the
next reader, and that is the failure this whole page is about.

### 4. The fixture sits where the failure is impossible

The one that took three attempts to expose, and the most instructive.

[`sprout`](https://github.com/ChelseaKR/sprout) had a determinism check.
Removing a `sorted()` left it green. Running the same command in **three
separate interpreters under different `PYTHONHASHSEED` values still left it
green** — because the fixture changed exactly one document, and one row has no
order to get wrong. Only widening the fixture to eight changed documents made
the control fire. Both dead ends are recorded in the test's own docstring in
[`tests/test_corpus_diff.py`](https://github.com/ChelseaKR/sprout/blob/main/tests/test_corpus_diff.py):

> Both halves of this fixture are load-bearing, and each was measured. […] With
> one changed document there is one row, and one row has no order, so the same
> control stayed green through three hash seeds. The failure has to be reachable
> before the check can find it: this fixture changes eight documents.

**When a control does not fire, widen the fixture before you doubt the
sabotage.** That is the rule this case exists to establish.

### 5. A stale `.pyc` runs after you restore the source

CPython invalidates cached bytecode on the source file's **modification time in
whole seconds plus its size**. A control that swaps one identifier for another
of *identical byte length* and restores it **within the same second** matches on
both, so the interpreter keeps executing the sabotaged bytecode after the source
on disk is already correct.

That run reports red after the restore and reads like a genuine regression. Had
the timing gone the other way — sabotage cached, source restored, cache reused —
it would have read as **a verified guard**. Both directions are wrong and
neither announces itself.

Clear `__pycache__` between every control run. Do not assume a restored file is
a restored program.

### 6. Two runs inside one interpreter

`test_output_is_byte_identical_across_runs` reads as a determinism gate and is
not one. Both renders happen in the same process, where iteration over a set of
strings is stable, so removing a `sorted()` is invisible to it.

A determinism claim has to be tested **across processes**, with `PYTHONHASHSEED`
varied. `sprout` now carries both forms side by side —
`test_output_is_byte_identical_across_runs` and
`test_output_is_byte_identical_across_processes` — and the second one launches
three subprocesses under seeds `0`, `1` and `12345`. With a hash-order
dependence planted, the in-process form printed a pass and the cross-process
form failed all three seeds.

## And one that is not about your code at all

The tool under test can filter your sabotage.

Reproduced on 2026-09-07 with TruffleHog 3.97.1, on a throwaway repository with a
real-shaped AWS key planted in one commit and deleted in the next — present in
history, absent at `HEAD`, which was asserted before reading any result:

```text
trufflehog git file://$D --results=verified                     --fail  exit 0,   0 findings
trufflehog git file://$D --results=verified,unknown             --fail  exit 0,   0 findings
trufflehog git file://$D --results=verified,unknown,unverified  --fail  exit 183, 1 finding
```

`unverified` means "I asked the service and it said no" — that is, a **revoked**
credential, which is the normal end state of a real leak. A history scan
configured to report only the first two tiers cannot fail on the very incident
it exists for.

The second half of that measurement is the point of this section, and it is case
1 wearing someone else's clothes. Repeating the identical experiment with AWS's
**documented example credential** (`AKIAIOSFODNN7EXAMPLE`) gives **0 findings and
exit 0 under all three tiers** — the scanner filters it. Plant that and your
control silently no-ops, and the run reads as a pass on a scanner you have just
proved nothing about.

So: before reading any such result, confirm the planted commit is present in
history and absent at `HEAD`, and check that the thing you planted is something
the tool is willing to see.

## What this does not buy you

- **It is not proof of correctness.** It establishes that a check can fail, and
  that it fails on the specific defect you planted. A suite can be observably
  falsifiable and still miss the defect you did not think of.
- **It does not scale to every assertion.** Plumbline runs 23 cases against 15
  suites, at the granularity of "this suite, this defect". Per-assertion
  mutation testing is a different and heavier instrument. If you reach for one,
  the design point worth stealing is this: generate mutants only on lines the
  suite **actually executed**, measured with a coverage run in the same
  invocation rather than assumed, and print the covered-line count so the
  denominator is visible. A mutant on a line nothing runs survives for a reason
  mutation testing was not asked about, and counting it as a survivor is this
  page's own subject in yet another costume.
- **It is not free.** [`tests/test_defect_matrix.py`](../tests/test_defect_matrix.py)
  rebuilds the whole matrix on every test run — one full audit per case plus the
  control, and the slowest thing in the suite by a wide margin. That is the
  deliberate trade, and the docstring says why: *"a fail-closed
  harness whose proof of being fail-closed is a stale committed file has the
  problem it exists to prevent."* If you adopt this and it is too slow for your
  suite, move it to a scheduled job rather than to a committed file nothing
  regenerates.

## The one-line version

*A claim that cannot come out differently is not a measurement.* Everything
above is machinery for finding out which kind you have.
