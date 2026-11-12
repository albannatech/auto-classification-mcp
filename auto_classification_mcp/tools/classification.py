"""The Frappe handlers — the only module here that imports Frappe.

Seven tools, and the shape of each is dictated by a primitive the core supplies
rather than by this extension's preference.

``classify_record``
    Takes a **privilege snapshot** and enqueues.  It does not read the record's
    fields inline, does not call a provider, and does not set anything.  It
    returns a draft name.

``apply_classification``
    The human decision, and the only place a real field is written.  It checks
    the caller's permission on the target through Frappe, and it refuses a
    submitted document outright — a submitted document has to be cancelled and
    amended, which nothing here does.

``override_classification``
    Keeps the reader's reason as a labelled example.  This is the only way the
    extension improves: a system that cannot be told it was wrong is a system
    that stays wrong.

The job itself
--------------
:func:`run_classification` is what the worker calls.  It reads the record's
configured fields, renders the classification prompt through the core's
**restricted template engine** so the record text arrives fenced, asks the
core's **provider**, and writes a **draft**.  Nothing here reaches past the core
for any of it, and nothing here runs inside a document hook.
"""

from __future__ import annotations

from typing import Any

import frappe

from albanna_ai_chat.core.jobs import JobRequest, RetryPolicy, validate_job
from albanna_ai_chat.core.port import ToolContext, ToolResult
from albanna_ai_chat.core.proposal import PromotionPolicy, review_reason
from albanna_ai_chat.core.template import TemplateProblem, render_data_only
from albanna_ai_chat.core.tools import ToolSpec, compact_json, validate_arguments
from albanna_ai_chat.services.jobs import JobRunner, audit, enqueue, snapshot_for

from auto_classification_mcp.tools.parsing import (
    AMBIGUOUS,
    NONE,
    ParseProblem,
    needs_review,
    parse_classification_response,
    summarise,
    validate_labels,
)

CLASSIFICATION_DOCTYPE = "Classification"
SETTINGS_DOCTYPE = "Auto Classification MCP Settings"

TOOL_NAMES = frozenset(
    {
        "list_classifications",
        "get_classification",
        "classify_record",
        "apply_classification",
        "revert_classification",
        "override_classification",
        "reclassify",
    }
)


class ClassificationBackend:
    """Runs this extension's seven tools."""

    def handles(self, name: str) -> bool:
        return name in TOOL_NAMES

    def call(
        self,
        spec: ToolSpec,
        arguments: dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        problem = validate_arguments(spec, arguments)
        if problem:
            return ToolResult.failure(problem, error="invalid_arguments")

        handler = getattr(self, f"_run_{spec.name}", None)
        if handler is None:  # pragma: no cover
            return ToolResult.failure(
                f"{spec.name} is not implemented.", error="not_implemented"
            )
        return handler(arguments, context)

    # ------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------

    def _run_list_classifications(
        self, arguments: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        filters = {}
        if arguments.get("status"):
            filters["status"] = arguments["status"]
        if arguments.get("doctype"):
            filters["target_doctype"] = arguments["doctype"]
        rows = frappe.get_list(
            CLASSIFICATION_DOCTYPE,
            filters=filters,
            fields=["name", "target_doctype", "target_name", "label", "confidence", "status"],
            limit_page_length=50,
        )
        return ToolResult.success(
            compact_json(rows), data=rows, summary=f"Found {len(rows)} classification(s)"
        )

    def _run_get_classification(
        self, arguments: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        name = arguments["name"]
        if not frappe.db.exists(CLASSIFICATION_DOCTYPE, name):
            return ToolResult.failure(
                f"No classification named {name!r}.", error="not_found"
            )
        doc = frappe.get_doc(CLASSIFICATION_DOCTYPE, name)
        payload = {
            "name": doc.name,
            "target_doctype": doc.get("target_doctype"),
            "target_name": doc.get("target_name"),
            "label": doc.get("label"),
            "confidence": doc.get("confidence"),
            "status": doc.get("status"),
            "model_version": doc.get("model_version"),
            "prompt_version": doc.get("prompt_version"),
            "override_reason": doc.get("override_reason"),
            "prior_value": doc.get("prior_value"),
        }
        return ToolResult.success(
            compact_json(payload), data=payload, summary=f"Classification {doc.name}"
        )

    # ------------------------------------------------------------------
    # the write that starts the work
    # ------------------------------------------------------------------

    def _run_classify_record(
        self, arguments: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        doctype, name = arguments["doctype"], arguments["name"]
        labels = self._labels(doctype)
        problem = validate_labels(labels)
        if problem:
            return ToolResult.failure(str(problem), error="no_labels")

        if not frappe.db.exists(doctype, name):
            return ToolResult.failure(
                f"No {doctype} named {name!r}.", error="not_found"
            )

        snapshot = snapshot_for(context.principal.user)
        request = JobRequest(
            extension="auto_classification_mcp",
            job="classify_record",
            payload={"doctype": doctype, "name": name, "labels": list(labels)},
            snapshot=snapshot,
            purpose=f"Classify {doctype}/{name} into one of {len(labels)} label(s).",
            retry=RetryPolicy(attempts=2, backoff_seconds=120),
        )
        problem = validate_job(request)
        if problem:
            return ToolResult.failure(str(problem), error="invalid_job")

        enqueue(request, "auto_classification_mcp.tools.classification.run_classification")
        return ToolResult.success(
            compact_json(
                {
                    "status": "queued",
                    "job": request.key,
                    "labels": list(labels),
                    "note": (
                        "Classification runs in the background. Nothing has "
                        "been written to the record — the result is a draft a "
                        "person reviews, or an operator rule applies."
                    ),
                }
            ),
            summary=f"Queued classification of {doctype}/{name}",
        )

    def _run_reclassify(
        self, arguments: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        return self._run_classify_record(arguments, context)

    # ------------------------------------------------------------------
    # the human decision
    # ------------------------------------------------------------------

    def _run_apply_classification(
        self, arguments: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        name = arguments["name"]
        if not frappe.db.exists(CLASSIFICATION_DOCTYPE, name):
            return ToolResult.failure(
                f"No classification named {name!r}.", error="not_found"
            )
        draft = frappe.get_doc(CLASSIFICATION_DOCTYPE, name)
        if draft.get("status") != "draft":
            return ToolResult.refusal(
                f"Classification {name} is {draft.get('status')}, not awaiting review.",
                error="not_a_draft",
            )

        doctype = draft.get("target_doctype")
        target = draft.get("target_name")
        field = draft.get("target_field")

        if not frappe.has_permission(doctype, "write", doc=target):
            return ToolResult.refusal(
                f"This account may not change {doctype}/{target}.", error="denied"
            )

        doc = frappe.get_doc(doctype, target)
        if doc.get("docstatus") == 1:
            # A submitted document cannot be edited.  It has to be cancelled
            # and amended, which this tool does not do — and saying so is the
            # correct answer rather than trying.
            return ToolResult.refusal(
                f"{doctype}/{target} is submitted and cannot be changed. It has "
                "to be cancelled and amended, which this tool does not do.",
                error="submitted",
            )

        prior = doc.get(field)
        doc.set(field, draft.get("label"))
        doc.save()
        draft.db_set({"status": "applied", "prior_value": prior})

        return ToolResult.success(
            compact_json({"status": "applied", "label": draft.get("label")}),
            summary=f"Applied {draft.get('label')} to {doctype}/{target}",
        )

    def _run_revert_classification(
        self, arguments: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        name = arguments["name"]
        if not frappe.db.exists(CLASSIFICATION_DOCTYPE, name):
            return ToolResult.failure(
                f"No classification named {name!r}.", error="not_found"
            )
        draft = frappe.get_doc(CLASSIFICATION_DOCTYPE, name)
        if draft.get("status") != "applied":
            return ToolResult.refusal(
                f"Classification {name} is {draft.get('status')}, not applied.",
                error="not_applied",
            )

        doctype = draft.get("target_doctype")
        target = draft.get("target_name")
        field = draft.get("target_field")
        doc = frappe.get_doc(doctype, target)
        doc.set(field, draft.get("prior_value"))
        doc.save()
        draft.db_set({"status": "reverted"})
        return ToolResult.success(
            compact_json({"status": "reverted"}),
            summary=f"Reverted classification {name}",
        )

    def _run_override_classification(
        self, arguments: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        name = arguments["name"]
        if not frappe.db.exists(CLASSIFICATION_DOCTYPE, name):
            return ToolResult.failure(
                f"No classification named {name!r}.", error="not_found"
            )
        draft = frappe.get_doc(CLASSIFICATION_DOCTYPE, name)
        draft.db_set(
            {
                "status": "overridden",
                "label": arguments["label"],
                "override_reason": arguments["reason"],
            }
        )
        return ToolResult.success(
            compact_json({"status": "overridden", "label": arguments["label"]}),
            summary=f"Overrode classification {name} to {arguments['label']}",
        )

    # ------------------------------------------------------------------
    # Frappe helpers
    # ------------------------------------------------------------------

    def _labels(self, doctype: str) -> list[str]:
        raw = self._settings().get("labels_by_doctype") or ""
        for line in str(raw).splitlines():
            if ":" not in line:
                continue
            name, labels = line.split(":", 1)
            if name.strip() == doctype:
                return [l.strip() for l in labels.split(",") if l.strip()]
        return []

    def _settings(self) -> dict:
        if not frappe.db.exists(SETTINGS_DOCTYPE, SETTINGS_DOCTYPE):
            return {}
        doc = frappe.get_doc(SETTINGS_DOCTYPE, SETTINGS_DOCTYPE)
        return {f: doc.get(f) for f in doc.meta.fields}


# ---------------------------------------------------------------------------
# The job the worker runs
# ---------------------------------------------------------------------------


def run_classification(request) -> Any:
    from albanna_ai_chat.services.jobs import run

    return run(request, _classify_under_snapshot)


def _classify_under_snapshot(runner: JobRunner):
    payload = runner.request.payload
    doctype, name = payload["doctype"], payload["name"]
    labels = list(payload["labels"])

    problem = validate_labels(labels)
    if problem:
        return runner.outcome(False, "No labels are configured.", str(problem))

    if not frappe.db.exists(doctype, name):
        return runner.outcome(False, f"{doctype}/{name} no longer exists.", "not_found")

    doc = frappe.get_doc(doctype, name)
    fields = ClassificationBackend()._settings().get("fields_by_doctype") or ""
    configured = _configured_fields(fields, doctype)
    record_text = " | ".join(
        f"{f}: {doc.get(f)}" for f in configured if doc.get(f) not in (None, "")
    )

    rendered = render_data_only(
        _classification_prompt(),
        {"record_text": record_text, "labels": ", ".join(labels)},
        allowed=("record_text", "labels"),
    )
    if isinstance(rendered, TemplateProblem):
        return runner.outcome(False, "The classification prompt is not valid.", str(rendered))

    provider = _provider()
    if provider is None:
        return runner.outcome(
            False, "No provider is configured for this extension.", "not_configured"
        )

    response = provider.complete(rendered.text)
    if not response.ok:
        return runner.outcome(False, "The provider could not answer.", response.error)

    parsed = parse_classification_response(response.text, labels)
    label = parsed.get("label") or ""
    confidence = parsed.get("confidence")

    runner.assert_may_write(CLASSIFICATION_DOCTYPE, "create")

    draft = frappe.get_doc(
        {
            "doctype": CLASSIFICATION_DOCTYPE,
            "target_doctype": doctype,
            "target_name": name,
            "target_field": _target_field(doctype),
            "label": label,
            "confidence": confidence,
            "status": "draft",
            "model_version": getattr(provider, "model", ""),
            "prompt_version": _prompt_version(),
            "purpose": runner.request.purpose,
        }
    )
    draft.insert(ignore_permissions=True)
    runner.record_change(CLASSIFICATION_DOCTYPE, draft.name)

    summary = summarise(label, confidence)
    audit(runner.request, runner.outcome(True, summary, changed=(draft.name,)))
    return runner.outcome(True, summary, changed=(draft.name,))


def _configured_fields(raw: str, doctype: str) -> list[str]:
    for line in str(raw).splitlines():
        if ":" not in line:
            continue
        name, fields = line.split(":", 1)
        if name.strip() == doctype:
            return [f.strip() for f in fields.split(",") if f.strip()]
    return []


def _target_field(doctype: str) -> str:
    raw = ClassificationBackend()._settings().get("target_field_by_doctype") or ""
    for line in str(raw).splitlines():
        if ":" not in line:
            continue
        name, field = line.split(":", 1)
        if name.strip() == doctype:
            return field.strip()
    return ""


def _classification_prompt() -> str:
    from auto_classification_mcp.agent import CLASSIFICATION_PROMPT

    return CLASSIFICATION_PROMPT


def _prompt_version() -> str:
    from albanna_ai_chat.core.proposal import input_digest
    from auto_classification_mcp.agent import CLASSIFICATION_PROMPT

    return input_digest(CLASSIFICATION_PROMPT)[:12]


def _provider():
    settings = ClassificationBackend()._settings()
    if not settings.get("provider"):
        return None
    from albanna_ai_chat.core.provider import NullProvider

    return NullProvider(model=str(settings.get("model") or ""))


def policy() -> PromotionPolicy:
    """This extension's promotion policy, from its settings.  Fails closed."""
    settings = ClassificationBackend()._settings()
    return PromotionPolicy(
        auto_accept=bool(settings.get("auto_accept")),
        threshold=float(settings.get("confidence_threshold") or 0.85),
        never_auto=tuple(
            f.strip()
            for f in str(settings.get("never_auto_fields") or "").splitlines()
            if f.strip()
        ),
    )


def why_waiting(draft) -> str:
    """Why *draft* is waiting for a person, in one readable sentence."""
    from albanna_ai_chat.core.proposal import Proposal

    proposal = Proposal(
        extension="auto_classification_mcp",
        doctype=draft.get("target_doctype"),
        name=draft.get("target_name") or "",
        values={draft.get("target_field") or "label": draft.get("label")},
        confidence=draft.get("confidence"),
    )
    return review_reason(proposal, policy())


def waits_for_review(draft) -> bool:
    """Whether *draft* needs a person, under this site's policy."""
    return needs_review(
        draft.get("label") or "",
        draft.get("confidence"),
        policy().threshold,
    )


__all__ = [
    "AMBIGUOUS",
    "NONE",
    "ClassificationBackend",
    "ParseProblem",
    "policy",
    "run_classification",
    "waits_for_review",
    "why_waiting",
]
