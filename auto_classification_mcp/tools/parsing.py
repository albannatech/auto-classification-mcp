"""Turning a model's answer into a label — pure, and tested without a site.

The classification prompt asks for one line: ``LABEL=<label>`` then
``CONFIDENCE=<0.00-1.00>``.  This module parses that, and it is the whole of the
parsing.

Why it is deliberately literal
------------------------------
A parser that "picks the best label" from prose is a parser that classifies.
The model's job is to choose; this module's job is to read what it chose.  A
label the model did not name exactly is not a label, and a confidence the model
did not give is not a confidence — ``None`` rather than a default, because a
model that cannot say how sure it is has not said it is sure.

``NONE`` and ``AMBIGUOUS`` are answers, not failures.  A record that fits no
label is a record the operator's label set does not cover, and the honest
response is to say so rather than to file it under the nearest one.
"""

from __future__ import annotations

import re

#: The two sentinel labels the prompt asks for.
NONE = "NONE"
AMBIGUOUS = "AMBIGUOUS"

_LABEL = re.compile(r"^\s*LABEL\s*=\s*(.*?)\s*$", re.IGNORECASE | re.MULTILINE)
_CONFIDENCE = re.compile(r"^\s*CONFIDENCE\s*=\s*(.*?)\s*$", re.IGNORECASE | re.MULTILINE)


class ParseProblem(str):
    """A response the parser refuses, as a sentence a developer can act on."""


def parse_classification_response(text: str, allowed: "list[str] | tuple[str, ...]") -> dict:
    """Parse *text* into ``{"label": ..., "confidence": ...}``.

    A label outside *allowed* is refused rather than coerced — a parser that
    mapped an unknown label onto the nearest allowed one would be classifying
    on the model's behalf, which is the one thing this module must not do.
    """
    label_match = _LABEL.search(str(text or ""))
    if not label_match:
        return {"label": "", "confidence": None}

    label = label_match.group(1).strip()
    if label and label not in allowed and label not in (NONE, AMBIGUOUS):
        return {"label": "", "confidence": None, "problem": f"unknown label {label!r}"}

    confidence_match = _CONFIDENCE.search(str(text or ""))
    confidence = None
    if confidence_match:
        try:
            confidence = float(confidence_match.group(1))
        except ValueError:
            confidence = None

    return {"label": label, "confidence": confidence}


def validate_labels(labels: "list[str] | tuple[str, ...]") -> ParseProblem | None:
    """Check the configured label set before a record is classified.

    An empty set is refused: classifying into nothing is either a bug or a way
    to spend a provider call and get a draft with no label in it.
    """
    if not labels:
        return ParseProblem(
            "a DocType must have at least one label configured — classifying "
            "into nothing spends a provider call and produces a draft with no "
            "label"
        )
    for label in labels:
        if not str(label).strip():
            return ParseProblem("a configured label is empty")
    return None


def needs_review(label: str, confidence, threshold: float) -> bool:
    """Whether a classification waits for a person.

    Fails closed in every direction: no confidence, a sentinel label, or a
    confidence under the threshold all mean review.  A classification that
    auto-applied because the model forgot to give a number would be a
    classification nobody authorised.
    """
    if label in (NONE, AMBIGUOUS) or not label:
        return True
    if confidence is None:
        return True
    return confidence < threshold


def summarise(label: str, confidence) -> str:
    """One line saying what the classification found, for the panel."""
    if label in (NONE, AMBIGUOUS):
        return f"Classified as {label}"
    if confidence is None:
        return f"Classified as {label} (no confidence given)"
    return f"Classified as {label} ({confidence:.2f})"
