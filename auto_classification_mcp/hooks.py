"""Frappe app hooks — the one file Frappe reads to wire this app in.

This app is an *extension* to the frappe-mcp core.  It contributes tools, an
agent and prompts, and it is installed and uninstalled like any other Frappe
app — which is the whole point of using a Frappe hook rather than a Python
entry point.

The one line that matters
-------------------------
``frappe_mcp_tools`` points at this app's manifest module.  The core resolves
that hook **per site**, validates it atomically, and absorbs the tools tagged
with this app's name.  Install this app and the chat gains a classification
agent; uninstall it and those tools are gone, and only those tools.

Why not a Python entry point
----------------------------
An entry point lives in the bench *virtualenv*, which every site on the bench
shares.  Install this extension there and its tools appear on every site
running the core — including sites that do not have this app installed, where
``Classification`` does not exist.  A Frappe hook is site-scoped, and the
scoping comes for free.

There are no document hooks here, and that is the decision
----------------------------------------------------------
The spec this extension was written from said *on submit → LLM classify → set
field → workflow*.  Every clause after the arrow is the defect, and the first
one is the reason this file is nearly empty.

``validate`` and ``on_submit`` run inside a document's transaction.  A model
call in either makes a third-party API a dependency of every save on the site:
a slow provider makes every write slow, and a down provider makes every write
**fail**, because a hook that raises rolls back the transaction.  So
classification is queued work the *tool* starts, never work a hook starts, and
the core's validator refuses an extension whose source reaches past it for a
provider.
"""

app_name = "auto_classification_mcp"
app_title = "Auto Classification MCP"
app_publisher = "Albanna Software Solutions"
app_description = (
    "Route tickets, tag leads, categorise expenses — the reference extension "
    "for classification that proposes and never mutates."
)
app_email = "ahmedalbanna966@gmail.com"
app_license = "mit"


# --------------------------------------------------------------------------
# The extension seam.
#
# The value is a dotted path to a module carrying TOOLS and TIERS.  The core
# imports it, validates it atomically, and absorbs it.
# --------------------------------------------------------------------------

frappe_mcp_tools = "auto_classification_mcp.tools.manifest"

# --------------------------------------------------------------------------
# The agent this extension brings.
#
# The core's prompt assembler reads this to build the system prompt when this
# extension's agent is the active one.  Pure data, so it is testable without
# a site.
# --------------------------------------------------------------------------

frappe_mcp_agent = "auto_classification_mcp.agent"

# The installer creates the Single settings row and the role, so the extension
# is usable and configurable the moment it is installed.
after_install = "auto_classification_mcp.install.after_install"
after_migrate = "auto_classification_mcp.install.after_migrate"

# --------------------------------------------------------------------------
# No ``doc_events``.
#
# Deliberately.  See the module docstring: a hook that classified inline would
# make a provider a dependency of every save on the site.  Classification is
# queued work the tool starts.
# --------------------------------------------------------------------------
