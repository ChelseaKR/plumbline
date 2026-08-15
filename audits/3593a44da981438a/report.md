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

| Suite | Score | Floor | Verdict | n | CI | MDE |
|---|---|---|---|---|---|---|
| accuracy | 0.8169 | 0.75 | **PASS** | 8 | pending (M2) | pending (M2) |
| refusal | 1.0000 | 0.90 | **PASS** | 12 | pending (M2) | pending (M2) |
| smoke | 1.0000 | 1.00 | **PASS** | 12 | pending (M2) | pending (M2) |

Overall verdict fails if any enabled suite fails.

## Warnings

- WARNING: item rb-004 (es): translation of rb-003 lacks subject-matter-expert review

## Notes

- **stats**: ci and mde are null pending milestone 2 (Wilson interval, minimum detectable effect); see DESIGN.md roadmap
- **reproducibility**: identical inputs and seed produce byte-identical reports; reports carry no timestamps by design
