# Changelog

All notable changes to Auto Classification MCP are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the app uses [semantic versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

**`REQUIRES_CORE` bumped to `>=0.4.0,<0.5.0`.**

The core shipped 0.4.0 with four bug fixes and no contract change, and this
extension still declared `>=0.3.0,<0.4.0` — so updating the core would have
refused its activation. The gate was right and the declaration was stale.

The new bound is earned rather than asserted: this extension's tests import the
real core and run its manifest through the core's own validator, and they pass
against 0.4.0.
## [0.1.0] — 2026-11-12

### Added

**The reference extension for classification that proposes and never mutates.**

Seven tools, one agent, two doctypes, no flow, and **no `doc_events` at all** —
the absence being the decision.

- `tools/manifest.py` — the contract. Imports no Frappe, so the core can
  validate it on a machine with none of this app's dependencies installed.
  `REQUIRES_CORE = ">=0.3.0,<0.4.0"`, the first core version carrying the async
  primitive and the draft-then-promote gate.
- `tools/parsing.py` — turning a model's answer into a label, deliberately
  literal. An unknown label is refused rather than coerced onto the nearest
  allowed one, because a parser that mapped it would be classifying on the
  model's behalf. A missing confidence is `None` rather than `0.0`, because a
  model that cannot say how sure it is has not said it is sure.
- `tools/classification.py` — the Frappe handlers, and the job the worker runs.
  `apply_classification` refuses a submitted document outright and says why.
- `agent.py` — persona, four boundaries, three prompts, and a deterministic
  `system_prompt()`.
- `hooks.py` — `frappe_mcp_tools`, `frappe_mcp_agent`, and no `doc_events`.
- Doctypes: `Classification`, `Auto Classification MCP Settings`.
- `install.py` — creates the role and the Single settings row, idempotently.
  The settings ship **empty**: no labels, no fields, no target field, no
  auto-accept.
- `tests/test_manifest.py`, `tests/test_classification.py` — 47 tests that
  import the **real core** and run this manifest through the core's own
  validator.

### The decisions it demonstrates

- **The model proposes; it never mutates.** Classification produces a draft.
  Applying it is a separate, permissioned, audited action.
- **The model never triggers a Workflow.** It proposes a state; a rule the
  operator wrote, or a person, confirms it.
- **Classification is queued, never inline.** `validate` and `on_submit` run
  inside the transaction, so a model call in either makes a third-party API a
  dependency of every save on the site.
- **The gate fails closed in every direction.** No confidence, a sentinel
  label, an empty label, or a confidence under the threshold all mean review.
- **Override is a first-class feature.** The reader's reason is kept as a
  labelled example, which is the only way this extension improves.

