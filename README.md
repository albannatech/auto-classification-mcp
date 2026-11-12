# Auto Classification MCP

Route tickets, tag leads, categorise expenses — **the reference extension for
classification that proposes and never mutates.**

An extension to [`albanna-ai-chat`](https://github.com/albannatech/albanna-ai-chat).
Install the core first; this app contributes tools, an agent and prompts to it.

```bash
bench get-app https://github.com/albannatech/auto-classification-mcp.git
bench --site {site} install-app auto_classification_mcp
```

---

## The load-bearing decision

**The model proposes. It never mutates, and it never triggers a Workflow.**

The spec this extension was written from said: *on submit → LLM classify → set
field → workflow*. Every clause after the arrow is the defect.

- **Setting a field on a submitted document** is the operation `albanna`'s
  `update_doc` explicitly refuses — a submitted document has to be cancelled and
  amended.
- **A Workflow fires its actions**: notifications, approvals, sometimes
  accounting entries. Handing that to a language model with no confidence
  threshold and no human gate is how a misrouted ticket becomes an incident.
- **`validate` and `on_submit` run inside the transaction.** A model call in
  either makes a third-party API a dependency of every save on the site: a slow
  provider makes every write slow, and a down provider makes every write
  **fail**, because a hook that raises rolls back the transaction.

So: classification produces a **draft**. Applying it is a separate, permissioned,
audited action. A Workflow transition is *proposed* and confirmed by a rule the
operator wrote, or by a person.

**This app has no `doc_events` at all**, and that absence is the decision.

---

## What it demonstrates

| Decision | Where |
|---|---|
| **Classification is queued, never inline** | `classify_record` enqueues with a privilege snapshot. No hook classifies. |
| **The gate fails closed** | No confidence → review. A sentinel label → review. Below threshold → review. |
| **A submitted document is never changed** | `apply_classification` refuses outright and says why. |
| **Override is a first-class feature** | The reader's reason is kept as a labelled example — the only way this extension improves. |
| **Every classification is versioned** | Model version and prompt version stored with the draft. |

### The surface

Seven tools, no flow — classify and apply is separated by a human decision or an
operator rule, and there is no transaction that spans either.

| Tool | Tier | Undone by |
|---|---|---|
| `list_classifications` | read | — |
| `get_classification` | read | — |
| `classify_record` | write | irreversible — says why |
| `apply_classification` | write | `revert_classification` |
| `revert_classification` | write | irreversible — says why |
| `override_classification` | write | irreversible — says why |
| `reclassify` | write | irreversible — says why |

---

## Configuration

`Auto Classification MCP Settings` (Single), **empty by default**:

| Field | Default | Why |
|---|---|---|
| `provider` / `model` | empty | No provider until configured. |
| `labels_by_doctype` | empty | One line per DocType. A DocType with no labels is not classified. |
| `fields_by_doctype` | empty | Which fields the classifier reads. |
| `target_field_by_doctype` | empty | Which field an applied classification writes. |
| `auto_accept` | **off** | The gate fails closed. |
| `confidence_threshold` | 0.85 | Only meaningful with auto-accept on. |

---

## Testing

```bash
python -m pytest tests/
```

47 tests. `test_classification.py` is the security-critical half: an unknown
label is refused rather than coerced onto the nearest allowed one, a missing
confidence is `None` rather than `0.0`, and the gate fails closed in every
direction.

The core is expected at `../albanna-ai-chat`; see `pythonpath` in
`pyproject.toml`.

---

## Requires core

`>=0.3.0,<0.4.0` — the first core version carrying the async primitive and the
draft-then-promote gate.
