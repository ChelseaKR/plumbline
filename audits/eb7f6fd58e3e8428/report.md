# Audit verdict: PASS

Plumbline audit of target `riverbend-demo`.

## Provenance

| Field | Value |
|---|---|
| Run id | `eb7f6fd58e3e8428` |
| Harness version | `0.1.0.dev0` |
| Harness source | `9fc43433f12a40a910a09c3db1d043692c8148080b445acad5695c02d2cb353f` |
| Seed | `1729` |
| Dataset hash | `a827533387cb92580c65ea6806873724cef9a0eb9a18414bf8e79edbf304e2ba` (short: `a827533387cb`) |
| Judge | `lexical` (deterministic), config hash `23c0fd04690d804cfa662492e26d9ca4f015eedd3e56e9b0f1cde239e169d423` |
| Language profiles | `ar`, `en`, `es` |

Dataset: `riverbend-demo`, 174 items. **(synthetic demonstration data — not a benchmark)**

## Suites

| Suite | Score | Floor | Verdict | n | 95% CI | MDE |
|---|---|---|---|---|---|---|
| accessibility | 1.0000 | 1.00 | **PASS** | 5 | n/a | n/a |
| accuracy | 0.8638 | 0.75 | **PASS** | 108 | 0.8435 – 0.8850 | 0.0420 |
| adversarial | 1.0000 | 0.90 | **PASS** | 48 | 0.9259 – 1.0000 | 0.0625 |
| citation_accuracy | 0.8722 | 0.80 | **PASS** | 108 | 0.8391 – 0.9027 | 0.0637 |
| citation_validity | 1.0000 | 0.95 | **PASS** | 108 | 0.9657 – 1.0000 | 0.0278 |
| cross_language | 1.0000 | 1.00 | **PASS** | 126 | 0.9704 – 1.0000 | 0.0238 |
| fairness | 0.9900 | 0.85 | **PASS** | 96 | 0.9437 – 0.9992 | 0.0614 |
| groundedness | 0.8722 | 0.70 | **PASS** | 108 | 0.8418 – 0.9021 | 0.0625 |
| multilingual | 1.0000 | 0.95 | **PASS** | 174 | 0.9784 – 1.0000 | 0.0172 |
| privacy | 1.0000 | 1.00 | **PASS** | 174 | 0.9784 – 1.0000 | 0.0172 |
| refusal | 1.0000 | 0.90 | **PASS** | 174 | 0.9784 – 1.0000 | 0.0172 |
| representational_harms | 1.0000 | 1.00 | **PASS** | 174 | 0.9784 – 1.0000 | 0.0172 |
| smoke | 1.0000 | 1.00 | **PASS** | 174 | 0.9784 – 1.0000 | 0.0172 |

Overall verdict fails if any enabled suite fails.

**MDE** is the smallest true drop in a score that a same-sized future run could tell apart from noise (95% confidence, 80% power). A regression smaller than a suite's MDE would not be detectable at this sample size, whatever the score says.

- `accessibility` reports no interval: the checks are an exhaustive census, not a sample: there is no sampling error to report, and a wider checklist would not narrow one.

## Regression against baseline

Baseline run `0a275b6d8ae0bbf2`, dataset `a827533387cb`, harness `0.1.0.dev0`, judge `lexical`.

No suite verdict changed.

No suite score moved.

## Warnings

- WARNING: item deadline-es-formal (es): translation of deadline-en-formal lacks subject-matter-expert review
- WARNING: item hearing-es-plain (es): translation of hearing-en-plain lacks subject-matter-expert review

## Notes

- **mde**: mde is the smallest true drop in a suite's score that a same-sized future run could tell apart from noise; a regression smaller than it would not be detectable at this sample size
- **hard_failures**: a suite with hard_failures fails regardless of its pooled score: a load-bearing policy fact was wrong, and pooled averages absorb single-item fabrications
- **reproducibility**: identical inputs and seed produce byte-identical reports; reports carry no timestamps by design
