"""Statistical honesty: confidence intervals and minimum detectable effect.

Every suite in every report carries two figures beyond its score:

- a **confidence interval** for the score at the sample size actually used, and
- a **minimum detectable effect (MDE)**: the smallest true drop in the score
  that a same-sized future run could distinguish from noise, at the configured
  confidence and power.

The MDE is the number that keeps a passing report honest. A suite can sit
comfortably above its floor and still be incapable of catching a regression
worth caring about, because the sample is too small. Printing the MDE next to
the score makes that visible instead of leaving it for the reader to infer.

Everything here is deterministic. Bootstrap resampling uses a SplitMix64
generator implemented in this file rather than `random`, so resamples depend
only on the run seed and never on the Python implementation's PRNG.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import NormalDist

# --- Chosen constants (demonstration defaults; see DESIGN.md) ---------------
CONFIDENCE = 0.95          # two-sided
POWER = 0.80               # 1 - beta
BOOTSTRAP_RESAMPLES = 2000  # enough for stable 2.5/97.5 percentiles, cheap offline
ROUND_DP = 4

# Score kinds a suite may declare. Each maps to an honest statistical
# treatment; a suite whose score is not a sample statistic says so rather than
# emitting an interval that would mislead.
KIND_PROPORTION = "proportion"  # score = successes / n over independent units
KIND_MEAN = "mean"              # score = mean of per-unit scores in [0, 1]
KIND_GAP = "gap"                # score = 1 - (max group mean - min group mean)
KIND_CENSUS = "census"          # score = fraction of a fixed, exhaustive checklist

_MASK64 = (1 << 64) - 1
_GOLDEN = 0x9E3779B97F4A7C15


class SplitMix64:
    """Small deterministic PRNG. Reproducible across platforms and Python
    versions because the algorithm lives here, not in the standard library."""

    def __init__(self, seed: int) -> None:
        self._state = seed & _MASK64

    def next_u64(self) -> int:
        self._state = (self._state + _GOLDEN) & _MASK64
        z = self._state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _MASK64
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _MASK64
        return (z ^ (z >> 31)) & _MASK64

    def below(self, n: int) -> int:
        """Uniform integer in [0, n) by rejection sampling (no modulo bias)."""
        if n <= 0:
            raise ValueError("below() requires n > 0")
        threshold = (1 << 64) % n
        while True:
            value = self.next_u64()
            if value >= threshold:
                return value % n


def z_two_sided(confidence: float = CONFIDENCE) -> float:
    """Critical value for a two-sided interval at `confidence`."""
    return NormalDist().inv_cdf(1.0 - (1.0 - confidence) / 2.0)


def z_power(power: float = POWER) -> float:
    return NormalDist().inv_cdf(power)


def wilson_interval(successes: int, n: int, confidence: float = CONFIDENCE
                    ) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion.

    Chosen over the normal ("Wald") interval because audit datasets are small
    and scores cluster near 1.0, exactly where Wald intervals are worst: they
    collapse to zero width at p = 1 and can run past 1.0 elsewhere.
    """
    if n <= 0:
        raise ValueError("wilson_interval requires n > 0")
    z = z_two_sided(confidence)
    p = successes / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z / denom) * sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, centre - half), min(1.0, centre + half))


def rule_of_three(n: int) -> float:
    """Upper bound on the true failure rate consistent with observing zero
    failures in n trials (the 95% "rule of three"). Used when a score is a
    perfect 1.0 or a flat 0.0: the normal approximation gives a variance of
    zero there, which would report an MDE of 0.0 and claim the run could
    detect an arbitrarily small regression. It cannot."""
    if n <= 0:
        raise ValueError("rule_of_three requires n > 0")
    return min(1.0, 3.0 / n)


def mde_from_se(se: float, n: int, *, confidence: float = CONFIDENCE,
                power: float = POWER) -> float:
    """Smallest detectable difference between two independent runs of size n,
    given the standard error of the statistic within one run.

    The comparison a reader cares about is run-vs-baseline, so the relevant
    standard error is that of the *difference* of two independent estimates:
    sqrt(2) * se.
    """
    if se <= 0.0:
        return rule_of_three(n)
    return min(1.0, (z_two_sided(confidence) + z_power(power)) * sqrt(2.0) * se)


def _percentile(sorted_values: list[float], q: float) -> float:
    """Linear-interpolated percentile of an already-sorted list."""
    if not sorted_values:
        raise ValueError("percentile of an empty sample")
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = q * (len(sorted_values) - 1)
    low = int(pos)
    high = min(low + 1, len(sorted_values) - 1)
    frac = pos - low
    return sorted_values[low] * (1 - frac) + sorted_values[high] * frac


def bootstrap(statistic, resample, *, seed: int,
              resamples: int = BOOTSTRAP_RESAMPLES,
              confidence: float = CONFIDENCE) -> tuple[tuple[float, float], float]:
    """Percentile bootstrap. Returns ((lower, upper), standard_error).

    `resample(rng)` draws one bootstrap replicate of the underlying data and
    `statistic(replicate)` reduces it to a score.
    """
    rng = SplitMix64(seed)
    draws = sorted(statistic(resample(rng)) for _ in range(resamples))
    alpha = (1.0 - confidence) / 2.0
    lower = _percentile(draws, alpha)
    upper = _percentile(draws, 1.0 - alpha)
    mean = sum(draws) / len(draws)
    variance = sum((d - mean) ** 2 for d in draws) / (len(draws) - 1)
    return (max(0.0, lower), min(1.0, upper)), sqrt(variance)


@dataclass
class Statistics:
    """What gets stamped onto a suite result."""
    ci: dict | None
    mde: float | None
    meta: dict


def _round(value: float) -> float:
    return round(value, ROUND_DP)


def _proportion_stats(sample: list[float], *, confidence: float, power: float
                      ) -> Statistics:
    n = len(sample)
    successes = round(sum(sample))
    p = successes / n
    lower, upper = wilson_interval(successes, n, confidence)
    if p in (0.0, 1.0):
        mde = rule_of_three(n)
        mde_method = (
            "rule of three: with no observed variation the normal "
            "approximation is unusable, so this is the smallest true failure "
            "rate the sample size could have ruled out"
        )
    else:
        mde = mde_from_se(sqrt(p * (1 - p) / n), n,
                          confidence=confidence, power=power)
        mde_method = "two-sample normal approximation, equal n, on a proportion"
    return Statistics(
        ci={"lower": _round(lower), "upper": _round(upper),
            "confidence": confidence, "method": "wilson score interval"},
        mde=_round(mde),
        meta={"score_kind": KIND_PROPORTION, "n": n, "successes": successes,
              "power": power, "mde_method": mde_method, "resamples": None},
    )


def _mean_stats(sample: list[float], *, seed: int, confidence: float,
                power: float, resamples: int) -> Statistics:
    n = len(sample)
    if n < 2:
        return Statistics(
            ci=None, mde=None,
            meta={"score_kind": KIND_MEAN, "n": n, "power": power,
                  "resamples": None,
                  "reason": "fewer than 2 scored units: no dispersion to "
                            "estimate, so any interval would be invented"},
        )

    if len(set(sample)) == 1:
        # Every unit scored identically. Resampling identical values yields
        # an interval of zero width, which would read as certainty the sample
        # has not earned. At an endpoint the sample is a run of successes (or
        # failures) and Wilson is the right instrument; anywhere else there is
        # genuinely no dispersion to reason from, and the report says so.
        value = sample[0]
        if value in (0.0, 1.0):
            lower, upper = wilson_interval(round(value * n), n, confidence)
            return Statistics(
                ci={"lower": _round(lower), "upper": _round(upper),
                    "confidence": confidence,
                    "method": "wilson score interval (every unit scored "
                              "identically at an endpoint)"},
                mde=_round(rule_of_three(n)),
                meta={"score_kind": KIND_MEAN, "n": n, "power": power,
                      "resamples": None,
                      "mde_method": "rule of three: no observed variation"},
            )
        return Statistics(
            ci=None, mde=_round(rule_of_three(n)),
            meta={"score_kind": KIND_MEAN, "n": n, "power": power,
                  "resamples": None,
                  "mde_method": "rule of three: no observed variation",
                  "reason": "every unit scored identically, so there is no "
                            "dispersion to resample and a bootstrap interval "
                            "would be zero width"},
        )

    def resample(rng: SplitMix64) -> list[float]:
        return [sample[rng.below(n)] for _ in range(n)]

    (lower, upper), se = bootstrap(
        lambda values: sum(values) / len(values), resample,
        seed=seed, resamples=resamples, confidence=confidence,
    )
    return Statistics(
        ci={"lower": _round(lower), "upper": _round(upper),
            "confidence": confidence, "method": "percentile bootstrap"},
        mde=_round(mde_from_se(se, n, confidence=confidence, power=power)),
        meta={"score_kind": KIND_MEAN, "n": n, "power": power,
              "resamples": resamples,
              "mde_method": "two-sample normal approximation, equal n, on a "
                            "bootstrap standard error"},
    )


def gap_score(strata: dict[str, list[float]]) -> float:
    """1 - (largest group mean - smallest group mean), clipped to [0, 1]."""
    means = [sum(values) / len(values) for values in strata.values() if values]
    if len(means) < 2:
        return 1.0
    return max(0.0, min(1.0, 1.0 - (max(means) - min(means))))


def _gap_stats(strata: dict[str, list[float]], *, seed: int, confidence: float,
               power: float, resamples: int) -> Statistics:
    n = sum(len(v) for v in strata.values())
    if any(len(v) < 2 for v in strata.values()) or len(strata) < 2:
        return Statistics(
            ci=None, mde=None,
            meta={"score_kind": KIND_GAP, "n": n, "power": power,
                  "resamples": None,
                  "reason": "every compared group needs at least 2 items "
                            "before a between-group gap can be resampled"},
        )
    keys = sorted(strata)

    def resample(rng: SplitMix64) -> dict[str, list[float]]:
        drawn = {}
        for key in keys:
            values = strata[key]
            drawn[key] = [values[rng.below(len(values))] for _ in values]
        return drawn

    (lower, upper), se = bootstrap(
        gap_score, resample, seed=seed, resamples=resamples,
        confidence=confidence,
    )
    return Statistics(
        ci={"lower": _round(lower), "upper": _round(upper),
            "confidence": confidence,
            "method": "percentile bootstrap, resampled within each group"},
        mde=_round(mde_from_se(se, n, confidence=confidence, power=power)),
        meta={"score_kind": KIND_GAP, "n": n, "power": power,
              "resamples": resamples,
              "mde_method": "two-sample normal approximation on a bootstrap "
                            "standard error of the between-group gap"},
    )


def compute(*, score_kind: str, sample: list[float],
            strata: dict[str, list[float]] | None, seed: int,
            confidence: float = CONFIDENCE, power: float = POWER,
            resamples: int = BOOTSTRAP_RESAMPLES) -> Statistics:
    """Statistics for one suite result. Called for every suite on every run;
    a suite cannot opt out, only declare a kind whose honest answer is
    "no interval applies here", with the reason recorded in the report."""
    if score_kind == KIND_CENSUS:
        return Statistics(
            ci=None, mde=None,
            meta={"score_kind": KIND_CENSUS, "n": len(sample), "power": power,
                  "resamples": None,
                  "reason": "the checks are an exhaustive census, not a "
                            "sample: there is no sampling error to report, "
                            "and a wider checklist would not narrow one"},
        )
    if score_kind == KIND_GAP:
        return _gap_stats(strata or {}, seed=seed, confidence=confidence,
                          power=power, resamples=resamples)
    if not sample:
        return Statistics(
            ci=None, mde=None,
            meta={"score_kind": score_kind, "n": 0, "power": power,
                  "resamples": None,
                  "reason": "no scored units"},
        )
    if score_kind == KIND_PROPORTION:
        return _proportion_stats(sample, confidence=confidence, power=power)
    if score_kind == KIND_MEAN:
        return _mean_stats(sample, seed=seed, confidence=confidence,
                           power=power, resamples=resamples)
    raise ValueError(f"unknown score kind '{score_kind}'")
