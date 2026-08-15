"""Confidence intervals, minimum detectable effect, and their determinism."""

import unittest

from plumbline.stats import (
    BOOTSTRAP_RESAMPLES,
    KIND_CENSUS,
    KIND_GAP,
    KIND_MEAN,
    KIND_PROPORTION,
    SplitMix64,
    compute,
    gap_score,
    mde_from_se,
    rule_of_three,
    wilson_interval,
    z_power,
    z_two_sided,
)


class PrngTests(unittest.TestCase):
    def test_same_seed_same_stream(self):
        a = [SplitMix64(7).next_u64() for _ in range(5)]
        b = [SplitMix64(7).next_u64() for _ in range(5)]
        self.assertEqual(a, b)

    def test_different_seed_different_stream(self):
        self.assertNotEqual(SplitMix64(7).next_u64(), SplitMix64(8).next_u64())

    def test_below_stays_in_range(self):
        rng = SplitMix64(1729)
        values = [rng.below(5) for _ in range(500)]
        self.assertTrue(all(0 <= v < 5 for v in values))
        self.assertEqual(len(set(values)), 5)  # every bucket is reachable


class CriticalValueTests(unittest.TestCase):
    def test_two_sided_95(self):
        self.assertAlmostEqual(z_two_sided(0.95), 1.959964, places=5)

    def test_power_80(self):
        self.assertAlmostEqual(z_power(0.80), 0.841621, places=5)


class WilsonTests(unittest.TestCase):
    def test_interval_brackets_the_point_estimate(self):
        lower, upper = wilson_interval(7, 10)
        self.assertLess(lower, 0.7)
        self.assertGreater(upper, 0.7)

    def test_stays_inside_zero_one_at_the_edges(self):
        lower, upper = wilson_interval(10, 10)
        self.assertGreaterEqual(lower, 0.0)
        self.assertLessEqual(upper, 1.0)
        self.assertLess(lower, 1.0)  # a perfect score is still uncertain

    def test_larger_sample_narrows_the_interval(self):
        small = wilson_interval(7, 10)
        large = wilson_interval(70, 100)
        self.assertLess(large[1] - large[0], small[1] - small[0])

    def test_zero_n_rejected(self):
        with self.assertRaises(ValueError):
            wilson_interval(0, 0)


class MdeTests(unittest.TestCase):
    def test_rule_of_three(self):
        self.assertAlmostEqual(rule_of_three(12), 0.25)
        self.assertEqual(rule_of_three(2), 1.0)  # clipped

    def test_zero_standard_error_falls_back_to_rule_of_three(self):
        self.assertAlmostEqual(mde_from_se(0.0, 12), 0.25)

    def test_mde_shrinks_as_n_grows(self):
        from math import sqrt
        small = mde_from_se(sqrt(0.25 / 10), 10)
        large = mde_from_se(sqrt(0.25 / 1000), 1000)
        self.assertLess(large, small)

    def test_small_sample_cannot_catch_small_regressions(self):
        stats = compute(score_kind=KIND_PROPORTION,
                        sample=[1.0] * 9 + [0.0], strata=None, seed=1)
        # 90% on ten items: a five-point regression is far below the noise.
        self.assertGreater(stats.mde, 0.05)


class ComputeTests(unittest.TestCase):
    def test_proportion_reports_wilson(self):
        stats = compute(score_kind=KIND_PROPORTION,
                        sample=[1.0] * 8 + [0.0, 0.0], strata=None, seed=1729)
        self.assertEqual(stats.ci["method"], "wilson score interval")
        self.assertEqual(stats.ci["confidence"], 0.95)
        self.assertEqual(stats.meta["successes"], 8)
        self.assertEqual(stats.meta["n"], 10)
        self.assertIsNotNone(stats.mde)

    def test_perfect_proportion_uses_rule_of_three(self):
        stats = compute(score_kind=KIND_PROPORTION, sample=[1.0] * 12,
                        strata=None, seed=1729)
        self.assertAlmostEqual(stats.mde, 0.25)
        self.assertIn("rule of three", stats.meta["mde_method"])
        # A perfect score still has a lower bound below 1.0.
        self.assertLess(stats.ci["lower"], 1.0)

    def test_mean_uses_bootstrap_and_is_deterministic(self):
        sample = [0.9, 0.8, 1.0, 0.6, 0.95, 0.7, 0.85, 0.75]
        first = compute(score_kind=KIND_MEAN, sample=sample, strata=None, seed=42)
        second = compute(score_kind=KIND_MEAN, sample=sample, strata=None, seed=42)
        self.assertEqual(first.ci, second.ci)
        self.assertEqual(first.mde, second.mde)
        self.assertEqual(first.ci["method"], "percentile bootstrap")
        self.assertEqual(first.meta["resamples"], BOOTSTRAP_RESAMPLES)
        self.assertLess(first.ci["lower"], sum(sample) / len(sample))
        self.assertGreater(first.ci["upper"], sum(sample) / len(sample))

    def test_bootstrap_resample_count_is_enough_to_be_seed_insensitive(self):
        # A reported figure that swings with the seed would be theatre. At
        # 2000 resamples the interval and the MDE agree across seeds to well
        # inside any floor decision; only the same-seed case is byte-exact.
        sample = [0.9, 0.8, 1.0, 0.6, 0.95, 0.7, 0.85, 0.75]
        runs = [compute(score_kind=KIND_MEAN, sample=sample, strata=None, seed=s)
                for s in (1, 2, 42, 1729, 999983)]
        for field in ("lower", "upper"):
            spread = (max(r.ci[field] for r in runs)
                      - min(r.ci[field] for r in runs))
            self.assertLess(spread, 0.01, f"{field} swings with the seed")
        self.assertLess(max(r.mde for r in runs) - min(r.mde for r in runs), 0.01)

    def test_flawless_mean_sample_does_not_report_a_zero_width_interval(self):
        stats = compute(score_kind=KIND_MEAN, sample=[1.0] * 18,
                        strata=None, seed=1729)
        self.assertLess(stats.ci["lower"], 1.0)
        self.assertIn("wilson", stats.ci["method"])
        self.assertAlmostEqual(stats.mde, round(3 / 18, 4))

    def test_mean_sample_flat_off_the_endpoints_refuses_an_interval(self):
        stats = compute(score_kind=KIND_MEAN, sample=[0.7] * 10,
                        strata=None, seed=1729)
        self.assertIsNone(stats.ci)
        self.assertIn("no dispersion to resample", stats.meta["reason"])
        self.assertAlmostEqual(stats.mde, 0.3)

    def test_mean_with_one_unit_refuses_an_interval(self):
        stats = compute(score_kind=KIND_MEAN, sample=[0.5], strata=None, seed=1)
        self.assertIsNone(stats.ci)
        self.assertIsNone(stats.mde)
        self.assertIn("dispersion", stats.meta["reason"])

    def test_empty_sample_refuses_an_interval(self):
        stats = compute(score_kind=KIND_PROPORTION, sample=[], strata=None, seed=1)
        self.assertIsNone(stats.ci)
        self.assertEqual(stats.meta["reason"], "no scored units")

    def test_census_refuses_an_interval_and_says_why(self):
        stats = compute(score_kind=KIND_CENSUS, sample=[1.0] * 5,
                        strata=None, seed=1)
        self.assertIsNone(stats.ci)
        self.assertIsNone(stats.mde)
        self.assertIn("census", stats.meta["reason"])

    def test_gap_score(self):
        self.assertAlmostEqual(gap_score({"a": [1.0, 1.0], "b": [0.8, 0.8]}), 0.8)
        self.assertEqual(gap_score({"a": [0.5]}), 1.0)  # nothing to compare

    def test_gap_bootstraps_within_groups(self):
        strata = {"formal": [1.0, 0.9, 0.95, 0.85], "colloquial": [0.8, 0.7, 0.9, 0.6]}
        stats = compute(score_kind=KIND_GAP, sample=[], strata=strata, seed=99)
        self.assertEqual(stats.meta["score_kind"], KIND_GAP)
        self.assertIsNotNone(stats.ci)
        self.assertLessEqual(stats.ci["lower"], stats.ci["upper"])
        self.assertEqual(stats.meta["n"], 8)

    def test_gap_refuses_when_a_group_is_too_small(self):
        stats = compute(score_kind=KIND_GAP, sample=[],
                        strata={"a": [1.0, 0.9], "b": [0.5]}, seed=1)
        self.assertIsNone(stats.ci)
        self.assertIn("at least 2 items", stats.meta["reason"])

    def test_unknown_kind_rejected(self):
        with self.assertRaises(ValueError):
            compute(score_kind="vibes", sample=[1.0], strata=None, seed=1)


if __name__ == "__main__":
    unittest.main()
