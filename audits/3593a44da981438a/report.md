# Audit verdict: PASS

Plumbline audit of target `riverbend-demo`.

## Provenance

| Field | Value |
|---|---|
| Run id | `3593a44da981438a` |
| Harness version | `0.1.0.dev0` |
| Seed | `1729` |
| Dataset hash | `129f0cf1bf06c43fa7f8762bdec87fb57f42c4440f8942ca880f85fbaec460ce` (short: `129f0cf1bf06`) |
| Judge | `lexical`, config hash `a7c8a5ee3457ae1dc4ed84f1031f1b3d0591abd25d0c9c21109d032d7092877b` |

Dataset: `riverbend-demo`, 12 items. **(synthetic demonstration data — not a benchmark)**

## Suites

| Suite | Score | Floor | Verdict | n | 95% CI | MDE |
|---|---|---|---|---|---|---|
| accuracy | 0.8169 | 0.75 | **PASS** | 8 | 0.6872 – 0.9201 | 0.2385 |
| refusal | 1.0000 | 0.90 | **PASS** | 12 | 0.7575 – 1.0000 | 0.2500 |
| smoke | 1.0000 | 1.00 | **PASS** | 12 | 0.7575 – 1.0000 | 0.2500 |

Overall verdict fails if any enabled suite fails.

**MDE** is the smallest true drop in a score that a same-sized future run could tell apart from noise (95% confidence, 80% power). A regression smaller than a suite's MDE would not be detectable at this sample size, whatever the score says.

## Warnings

- WARNING: item rb-004 (es): translation of rb-003 lacks subject-matter-expert review

## Notes

- **mde**: mde is the smallest true drop in a suite's score that a same-sized future run could tell apart from noise; a regression smaller than it would not be detectable at this sample size
- **hard_failures**: a suite with hard_failures fails regardless of its pooled score: a load-bearing policy fact was wrong, and pooled averages absorb single-item fabrications
- **reproducibility**: identical inputs and seed produce byte-identical reports; reports carry no timestamps by design
