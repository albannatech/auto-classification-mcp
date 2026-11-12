"""The security-critical half: the parser is literal and the gate fails closed.

The failure these guard against is not a crash — it is a classification applied
to a record nobody reviewed, or a label the model never actually chose.
"""

import pytest

from auto_classification_mcp.tools.parsing import (
    AMBIGUOUS,
    NONE,
    ParseProblem,
    needs_review,
    parse_classification_response,
    summarise,
    validate_labels,
)

LABELS = ["billing", "technical", "other"]


# ---------------------------------------------------------------------------
# The parser reads what the model chose, and nothing else
# ---------------------------------------------------------------------------


class TestTheParser:
    def test_it_reads_label_and_confidence(self):
        parsed = parse_classification_response(
            "LABEL=billing\nCONFIDENCE=0.93", LABELS
        )
        assert parsed["label"] == "billing"
        assert parsed["confidence"] == 0.93

    def test_an_unknown_label_is_refused_rather_than_coerced(self):
        # A parser that mapped an unknown label onto the nearest allowed one
        # would be classifying on the model's behalf.
        parsed = parse_classification_response("LABEL=refund", LABELS)
        assert parsed["label"] == ""
        assert "unknown label" in parsed.get("problem", "")

    def test_none_is_an_answer_not_a_failure(self):
        parsed = parse_classification_response("LABEL=NONE", LABELS)
        assert parsed["label"] == NONE

    def test_ambiguous_is_an_answer_not_a_failure(self):
        parsed = parse_classification_response("LABEL=AMBIGUOUS", LABELS)
        assert parsed["label"] == AMBIGUOUS

    def test_a_missing_confidence_is_none_not_zero(self):
        # A model that cannot say how sure it is has not said it is sure.
        parsed = parse_classification_response("LABEL=billing", LABELS)
        assert parsed["confidence"] is None

    def test_an_unparseable_confidence_is_none(self):
        parsed = parse_classification_response(
            "LABEL=billing\nCONFIDENCE=quite sure", LABELS
        )
        assert parsed["confidence"] is None

    def test_prose_is_not_mistaken_for_a_label(self):
        parsed = parse_classification_response(
            "This looks like a billing issue to me.", LABELS
        )
        assert parsed["label"] == ""

    def test_the_label_match_is_case_insensitive_on_the_key(self):
        parsed = parse_classification_response("label=billing", LABELS)
        assert parsed["label"] == "billing"


# ---------------------------------------------------------------------------
# The gate fails closed in every direction
# ---------------------------------------------------------------------------


class TestTheGateFailsClosed:
    def test_no_confidence_means_review(self):
        assert needs_review("billing", None, 0.85) is True

    def test_a_sentinel_label_means_review(self):
        assert needs_review(NONE, 0.99, 0.85) is True
        assert needs_review(AMBIGUOUS, 0.99, 0.85) is True

    def test_an_empty_label_means_review(self):
        assert needs_review("", 0.99, 0.85) is True

    def test_below_the_threshold_means_review(self):
        assert needs_review("billing", 0.5, 0.85) is True

    def test_at_the_threshold_does_not_need_review(self):
        assert needs_review("billing", 0.85, 0.85) is False

    def test_above_the_threshold_does_not_need_review(self):
        assert needs_review("billing", 0.95, 0.85) is False


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_an_empty_label_set_is_refused(self):
        problem = validate_labels([])
        assert isinstance(problem, ParseProblem)
        assert "at least one label" in problem

    def test_an_empty_label_is_refused(self):
        problem = validate_labels(["billing", "  "])
        assert isinstance(problem, ParseProblem)

    def test_a_well_formed_label_set_is_accepted(self):
        assert validate_labels(LABELS) is None


# ---------------------------------------------------------------------------
# The summary
# ---------------------------------------------------------------------------


class TestTheSummary:
    def test_it_names_the_label_and_the_confidence(self):
        assert summarise("billing", 0.93) == "Classified as billing (0.93)"

    def test_it_says_so_when_there_is_no_confidence(self):
        assert "no confidence" in summarise("billing", None)

    def test_a_sentinel_is_named_as_itself(self):
        assert summarise(NONE, None) == f"Classified as {NONE}"
