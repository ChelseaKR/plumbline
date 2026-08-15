import unittest

from plumbline.hashing import bundle_digest, config_digest, sha256_text, short_id


class HashingTests(unittest.TestCase):
    def test_sha256_text_stable(self):
        self.assertEqual(sha256_text("plumb"), sha256_text("plumb"))
        self.assertNotEqual(sha256_text("plumb"), sha256_text("line"))

    def test_bundle_digest_order_independent(self):
        a = {"x.jsonl": "aa", "y.jsonl": "bb"}
        b = {"y.jsonl": "bb", "x.jsonl": "aa"}
        self.assertEqual(bundle_digest(a), bundle_digest(b))

    def test_bundle_digest_content_sensitive(self):
        self.assertNotEqual(
            bundle_digest({"x": "aa"}), bundle_digest({"x": "ab"})
        )

    def test_config_digest_key_order_independent(self):
        self.assertEqual(
            config_digest({"a": 1, "b": [1, 2]}),
            config_digest({"b": [1, 2], "a": 1}),
        )

    def test_short_id_is_prefix(self):
        digest = sha256_text("anything")
        self.assertTrue(digest.startswith(short_id(digest)))
        self.assertEqual(len(short_id(digest)), 12)


if __name__ == "__main__":
    unittest.main()
