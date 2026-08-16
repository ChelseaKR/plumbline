"""Errors that can only happen when Plumbline talks to something outside
itself.

They live in their own dependency-free module for a structural reason: the CLI
has to be able to catch them, and importing the adapter package to get at its
exception class would drag the network code into every `plumbline gate` run.
The gate never imports an adapter, and this is part of how that stays true.

All of these map to the configuration/environment exit code. A target that
cannot be reached, an adapter that is misconfigured, a model judge with no
answer for an item: none of them are a scoring result, and none of them may be
reported as one.
"""

from __future__ import annotations


class OutboundError(Exception):
    """Base for adapter, network and model-judge failures (exit 4)."""
