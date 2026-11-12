"""Classification — one label a model proposed for a record."""

from __future__ import annotations

import frappe
from frappe.model.document import Document


class Classification(Document):
    """A draft, never a mutation. ``apply_classification`` is the only thing
    that writes the target field, and it checks the caller's permission on
    the target rather than inheriting it from whoever queued the work."""
