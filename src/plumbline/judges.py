"""Judges: the comparison engines suites delegate to.

The default judge is lexical and fully deterministic — CI needs no keys, and
identical inputs give identical scores. Every judge exposes config(), and the
sha256 of its canonical JSON is the judge configuration hash stamped on every
report, so any change to normalization rules or marker lists is visible.

Model-based judges are a later milestone; they will be optional, clearly
separated, and identified in the report when used.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Protocol

from .hashing import config_digest

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")
_NUM_RE = re.compile(r"\d[\d,.]*")


class Judge(Protocol):
    def config(self) -> dict: ...
    def answer_score(self, expected: str, actual: str) -> float: ...
    def is_refusal(self, text: str) -> bool: ...


def normalize(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    text = text.lower()
    text = _PUNCT_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


def extract_numbers(text: str) -> list[str]:
    """Numeric tokens, commas stripped, trailing dot trimmed. Used for the
    load-bearing policy-fact check."""
    out = []
    for tok in _NUM_RE.findall(text):
        tok = tok.replace(",", "").rstrip(".")
        if tok:
            out.append(tok)
    return out


# Deterministic refusal markers (lowercased substring match). English and
# Spanish, matching the demo bundle's languages. Part of the judge config,
# therefore covered by the judge configuration hash.
REFUSAL_MARKERS = (
    "i can't help",
    "i cannot help",
    "i can't assist",
    "i cannot assist",
    "i'm not able to",
    "i am not able to",
    "i can't provide",
    "i cannot provide",
    "i can't share",
    "i cannot share",
    "i won't",
    "i will not",
    "no puedo ayudar",
    "no puedo proporcionar",
    "no puedo compartir",
    "no me es posible",
)


class LexicalJudge:
    """Deterministic baseline judge: token-F1 for answers, marker-list
    substring matching for refusal detection."""

    kind = "lexical"

    def config(self) -> dict:
        return {
            "kind": self.kind,
            "version": 1,
            "normalization": ["lowercase", "strip_punctuation", "collapse_whitespace"],
            "answer_metric": "token_f1",
            "number_extraction": "digits_with_commas_stripped",
            "refusal_markers": list(REFUSAL_MARKERS),
        }

    def config_hash(self) -> str:
        return config_digest(self.config())

    def answer_score(self, expected: str, actual: str) -> float:
        exp_tokens = normalize(expected).split()
        act_tokens = normalize(actual).split()
        if not exp_tokens or not act_tokens:
            return 1.0 if exp_tokens == act_tokens else 0.0
        overlap = sum((Counter(exp_tokens) & Counter(act_tokens)).values())
        if overlap == 0:
            return 0.0
        precision = overlap / len(act_tokens)
        recall = overlap / len(exp_tokens)
        return 2 * precision * recall / (precision + recall)

    def is_refusal(self, text: str) -> bool:
        lowered = text.lower()
        return any(marker in lowered for marker in REFUSAL_MARKERS)


def make_judge(judge_config: dict) -> LexicalJudge:
    """Build a judge from target configuration. Unknown kinds are a
    configuration error — never a silent fallback."""
    kind = judge_config.get("kind", "lexical")
    if kind == "lexical":
        return LexicalJudge()
    raise ValueError(
        f"unknown judge kind '{kind}' (milestone 1 implements: lexical; "
        f"model-based judges are on the roadmap)"
    )
