"""The installer — what has to exist before this extension is usable.

Two things, both idempotent, because a restored site repairs itself on the next
migrate rather than failing on a missing document the first time somebody opens
the widget.

The settings row ships **empty**: no labels, no configured fields, no target
field, no auto-accept.  That is the whole of the "the operator decides" rule —
an extension that installed itself ready to classify every record on the site
would be an extension that made a decision nobody authorised.
"""

from __future__ import annotations

import frappe

CORE_APP = "albanna_ai_chat"
ROLE = "Auto Classification MCP User"
SETTINGS = "Auto Classification MCP Settings"


def after_install() -> None:
    _require_core()
    _ensure_role()
    _ensure_settings()


def after_migrate() -> None:
    """Called on every migrate, so a restored site repairs itself."""
    _require_core()
    _ensure_role()
    _ensure_settings()


def _ensure_role() -> None:
    if frappe.db.exists("Role", ROLE):
        return
    frappe.get_doc({"doctype": "Role", "role_name": ROLE, "desk_access": 1}).insert(
        ignore_permissions=True
    )


def _ensure_settings() -> None:
    """The Single settings row, empty by default.

    ``labels_by_doctype`` is empty and there is no default set: an operator
    writes one line per DocType naming the labels it may be classified into.
    A DocType with no labels is a DocType that is not classified, which is the
    correct default.
    """
    if frappe.db.exists(SETTINGS, SETTINGS):
        return
    frappe.get_doc(
        {
            "doctype": SETTINGS,
            # No provider until configured.
            "provider": "",
            "model": "",
            # One line per DocType: ``Issue: billing, technical, other``.
            # Empty until an operator writes it.
            "labels_by_doctype": "",
            # One line per DocType: ``Issue: customer, subject, description``.
            "fields_by_doctype": "",
            # One line per DocType: ``Issue: category``.
            "target_field_by_doctype": "",
            # Review by default.  The gate fails closed.
            "auto_accept": 0,
            "confidence_threshold": 0.85,
            # Labels that may never be auto-accepted, whatever the confidence.
            "never_auto_fields": "",
        }
    ).insert(ignore_permissions=True)


def _require_core() -> None:
    """Refuse to install without the core, and say which app to install.

    A raised exception here fails the install, which is correct: an extension
    whose tools cannot be discovered is not an extension, it is a directory.
    """
    if CORE_APP in frappe.get_installed_apps():
        return
    frappe.throw(
        f"This extension requires the frappe-mcp core. Install it first: "
        f"bench get-app https://github.com/albannatech/albanna-ai-chat.git "
        f"&& bench --site {{site}} install-app {{CORE_APP}}",
        title="Missing required app",
    )
