"""What this extension contributes to the core — the whole contract.

An extension is a Frappe app that implements the ``frappe_mcp_tools`` hook.
This module is what that hook points at: ``TOOLS`` (a list of ``ToolSpec``)
and ``TIERS`` (every name classified).  The core validates both atomically and
absorbs them tagged with this app's name, so uninstalling removes exactly these
tools and nothing else.

Why the surface looks like this
-------------------------------
Seven tools, no flow.  Classification is queued work whose result is a *draft*,
and the step that would make it a flow — classify and then apply — is separated
by a human decision or an explicit operator rule.  There is no transaction that
spans either.

The load-bearing decision is not in this file
---------------------------------------------
**The model proposes. It never mutates, and it never triggers a Workflow.**

The spec this extension was written from said: *on submit → LLM classify → set
field → workflow*.  Every clause after the arrow is the defect.  Setting a field
on a submitted document is the operation `albanna`'s `update_doc` explicitly
refuses — a submitted document has to be cancelled and amended.  And a Workflow
fires its actions: notifications, approvals, sometimes accounting entries.
Handing that to a language model with no confidence threshold and no human gate
is how a misrouted ticket becomes an incident.

So: classification produces a draft. Applying it is a separate, permissioned,
audited action. A Workflow transition is *proposed* and confirmed by a rule the
operator wrote, or by a person.

Nothing here imports Frappe
---------------------------
The manifest is the contract, and the contract must be importable on a machine
with none of this app's dependencies installed — that is what lets the core
validate it before anything runs.  The handlers live in ``classification.py``.
"""

from __future__ import annotations

from albanna_ai_chat.core.flow import CompensationSpec
from albanna_ai_chat.core.tools import READ, WRITE, ToolSpec

#: The DocTypes this extension owns.  One module, and the doctypes its domain
#: actually has — not one doctype per tool.
CLASSIFICATION = "Classification"
SETTINGS = "Auto Classification MCP Settings"


def _schema(properties: dict, required: list[str]) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": required,
    }


# --------------------------------------------------------------------------
# Reads
# --------------------------------------------------------------------------

LIST_CLASSIFICATIONS = ToolSpec(
    name="list_classifications",
    description=(
        "List classification drafts, optionally only those waiting for review. "
        "Use this to answer 'what is waiting for me', 'what did we classify "
        "this week', 'which classifications were overridden'. Returns each "
        "draft's proposed label, its confidence, and its status."
    ),
    parameters=_schema(
        {
            "status": {
                "type": "string",
                "description": (
                    "Filter by status: draft, applied, overridden, rejected. "
                    "Omit for every status."
                ),
            },
            "doctype": {
                "type": "string",
                "description": "Filter by the DocType classified. Omit for all.",
            },
        },
        [],
    ),
    tier=READ,
)

GET_CLASSIFICATION = ToolSpec(
    name="get_classification",
    description=(
        "Fetch one classification draft by name, with its proposed label, "
        "confidence, the model and prompt version that produced it, and any "
        "override reason. Use this before applying, so the reader sees exactly "
        "what would change."
    ),
    parameters=_schema(
        {"name": {"type": "string", "description": "The draft's name."}},
        ["name"],
    ),
    tier=READ,
)


# --------------------------------------------------------------------------
# The write that starts the work
# --------------------------------------------------------------------------

CLASSIFY_RECORD = ToolSpec(
    name="classify_record",
    description=(
        "Classify a record into one of the labels configured for its DocType. "
        "The work runs in the background — this call returns the draft's name, "
        "not the label. Nothing is written to the record: the result is a draft "
        "a person reviews, or an operator rule applies. Say that, rather than "
        "implying the record has been tagged."
    ),
    parameters=_schema(
        {
            "doctype": {
                "type": "string",
                "description": "The DocType to classify, e.g. 'Issue', 'Lead'.",
            },
            "name": {
                "type": "string",
                "description": "The record's name, e.g. 'ISS-00042'.",
            },
        },
        ["doctype", "name"],
    ),
    tier=WRITE,
    doctype_arg="doctype",
    write_permission="read",
    # A classification is derived data about a record. Discarding it changes
    # nothing but the draft itself, and the record it describes is untouched.
    compensation=CompensationSpec(
        mechanism="none",
        reason=(
            "A classification is a draft derived from a record. Discarding it "
            "changes nothing but the draft — the record it describes is "
            "untouched, and re-classifying produces a fresh one."
        ),
    ),
)


# --------------------------------------------------------------------------
# The human decision
# --------------------------------------------------------------------------

APPLY_CLASSIFICATION = ToolSpec(
    name="apply_classification",
    description=(
        "Apply a reviewed classification draft to its record, setting the "
        "configured field to the proposed label. Use this only after the reader "
        "has seen the draft and agreed — or when an operator rule has "
        "auto-accepted it. A submitted document is never changed this way: it "
        "has to be cancelled and amended, which this tool does not do. Say so "
        "rather than trying."
    ),
    parameters=_schema(
        {"name": {"type": "string", "description": "The draft's name."}},
        ["name"],
    ),
    tier=WRITE,
    doctype_arg="doctype",
    write_permission="write",
    # The draft records the field's prior value, so reverting is a real inverse.
    compensation=CompensationSpec(
        mechanism="reverse", undo_with=("revert_classification",)
    ),
)

REVERT_CLASSIFICATION = ToolSpec(
    name="revert_classification",
    description=(
        "Undo an applied classification: restore the field's prior value. Use "
        "this when an applied classification turns out to have been wrong."
    ),
    parameters=_schema(
        {"name": {"type": "string", "description": "The draft's name."}},
        ["name"],
    ),
    tier=WRITE,
    write_permission="write",
    compensation=CompensationSpec(
        mechanism="none",
        reason=(
            "Reverting replaces the applied label with the prior one. "
            "Re-reverting would need the applied label, which this action has "
            "already overwritten; the draft's own history is the record."
        ),
    ),
)

OVERRIDE_CLASSIFICATION = ToolSpec(
    name="override_classification",
    description=(
        "Override a classification with the label the reader says is right, and "
        "record why. Use this when the model was wrong. The reason is kept as a "
        "labelled example, so the next classification of a similar record can "
        "be shown what was wrong — which is the only way this extension learns "
        "from its mistakes."
    ),
    parameters=_schema(
        {
            "name": {"type": "string", "description": "The draft's name."},
            "label": {
                "type": "string",
                "description": "The label the reader says is correct.",
            },
            "reason": {
                "type": "string",
                "description": "Why the model's label was wrong.",
            },
        },
        ["name", "label", "reason"],
    ),
    tier=WRITE,
    write_permission="write",
    compensation=CompensationSpec(
        mechanism="none",
        reason=(
            "An override is kept as a labelled example of what was wrong. "
            "Un-overriding it would discard the reason, which is the only part "
            "worth keeping."
        ),
    ),
)

RECLASSIFY = ToolSpec(
    name="reclassify",
    description=(
        "Re-classify a record under the current model and prompt. Use this "
        "after the model or the prompt changes, because a classification made "
        "by an older prompt is a classification made by different rules. The "
        "work runs in the background."
    ),
    parameters=_schema(
        {
            "doctype": {"type": "string", "description": "The DocType."},
            "name": {"type": "string", "description": "The record's name."},
        },
        ["doctype", "name"],
    ),
    tier=WRITE,
    doctype_arg="doctype",
    write_permission="read",
    compensation=CompensationSpec(
        mechanism="none",
        reason=(
            "Re-classifying replaces a derived draft. The record is untouched, "
            "so there is nothing to undo — only something to redo."
        ),
    ),
)


#: Every tool this extension contributes.
TOOLS = [
    LIST_CLASSIFICATIONS,
    GET_CLASSIFICATION,
    CLASSIFY_RECORD,
    APPLY_CLASSIFICATION,
    REVERT_CLASSIFICATION,
    OVERRIDE_CLASSIFICATION,
    RECLASSIFY,
]

#: Every tool classified.  The validator refuses a tool that is not here, so
#: this dict and TOOLS are kept in step by a test rather than by memory.
TIERS = {
    "list_classifications": READ,
    "get_classification": READ,
    "classify_record": WRITE,
    "apply_classification": WRITE,
    "revert_classification": WRITE,
    "override_classification": WRITE,
    "reclassify": WRITE,
}

#: The core version range this extension is built against.
#:
#: ``0.3.0`` is the first core version carrying the async primitive and the
#: draft-then-promote gate this extension depends on.  Classification is queued
#: work with a privilege snapshot, and its output is a proposal a person or an
#: operator rule disposes of.  An earlier core has neither.
REQUIRES_CORE = ">=0.3.0,<0.4.0"
