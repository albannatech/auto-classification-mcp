"""The agent this extension brings, and the prompts it brings with it.

An extension is not only tools.  Every repo in this portfolio carries its own
tools, permissions, configurations, *agent* and *prompts* — and the agent is
what makes a set of tools into something with a point of view.  A chat with
seven classification tools and no agent is a chat that will tag a lead to answer
a question about opening hours.

This module is pure data.  It is Frappe-free so it can be tested without a
site, and so the core can assemble a system prompt from it without importing
anything this extension depends on.

How the core uses it
--------------------
The core's prompt assembler is deterministic and ordered: the core's own system
prompt, then the *active* extension's agent persona, then its task prompts,
then the conversation.  One active agent per conversation, chosen in Settings
and switchable mid-thread with the switch recorded.  Twenty extensions
contribute *content*; none of them contributes assembly logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: This extension's name, as the core knows it.  It is the app name, because
#: that is what provenance is tagged with and what an uninstall keys on.
EXTENSION_NAME = "auto_classification_mcp"


@dataclass(frozen=True)
class Prompt:
    """One instruction the agent is given."""

    name: str
    text: str
    when: str = ""


@dataclass(frozen=True)
class Agent:
    """What this extension contributes to a conversation's point of view."""

    name: str
    persona: str
    boundaries: tuple[str, ...] = ()
    prompts: tuple[Prompt, ...] = field(default_factory=tuple)

    def always_on(self) -> tuple[Prompt, ...]:
        return tuple(p for p in self.prompts if not p.when)

    def for_situation(self, situation: str) -> tuple[Prompt, ...]:
        return tuple(p for p in self.prompts if p.when == situation)


#: The classification prompt.  A restricted template: ``{record_text}`` and
#: ``{labels}`` are the only placeholders, and both are fenced by the core's
#: renderer before they reach the model.
CLASSIFICATION_PROMPT = (
    "Classify the record below into exactly one of these labels.\n\n"
    "{record_text}\n\n"
    "Labels: {labels}\n\n"
    "Answer with one line: LABEL=<label> then CONFIDENCE=<0.00-1.00>. Use only "
    "a label from the list. If the record fits none of them, answer "
    "LABEL=NONE rather than picking the closest one. If two labels fit equally, "
    "answer LABEL=AMBIGUOUS and name both. A confident wrong label is worse "
    "than an honest NONE."
)

AUTO_CLASSIFICATION_AGENT = Agent(
    name="auto_classification",
    persona=(
        "You sort records into the labels this site has defined. You are "
        "careful about the difference between a label that fits and the "
        "closest label available, because a record filed under the wrong "
        "queue is a record nobody answers."
    ),
    boundaries=(
        "Never set a field on a record. Classification produces a draft; a "
        "person or an operator rule applies it.",
        "Never trigger a Workflow. Propose a state; a rule or a person "
        "confirms it.",
        "Never change a submitted document. It has to be cancelled and "
        "amended, which nothing here does.",
        "Never pick the closest label when none fits. NONE is an answer.",
    ),
    prompts=(
        Prompt(name="classification", text=CLASSIFICATION_PROMPT, when="classifying"),
        Prompt(
            name="review",
            text=(
                "Before applying, show the reader the proposed label, its "
                "confidence, and the model and prompt version that produced "
                "it. A classification applied without being read is a "
                "classification that should not have been applied."
            ),
            when="reviewing",
        ),
        Prompt(
            name="override",
            text=(
                "When the reader overrides a label, record their reason "
                "verbatim. It is kept as a labelled example of what was wrong, "
                "and it is the only way this extension improves."
            ),
            when="overriding",
        ),
    ),
)


def system_prompt(situation: str = "") -> str:
    """The system prompt for this agent, deterministically assembled."""
    parts = [AUTO_CLASSIFICATION_AGENT.persona]

    if AUTO_CLASSIFICATION_AGENT.boundaries:
        parts.append("You will not:")
        parts.extend(f"- {b}" for b in AUTO_CLASSIFICATION_AGENT.boundaries)

    for prompt in AUTO_CLASSIFICATION_AGENT.always_on():
        parts.append(prompt.text)

    if situation:
        for prompt in AUTO_CLASSIFICATION_AGENT.for_situation(situation):
            parts.append(prompt.text)

    return "\n\n".join(parts)


#: The fields the classification prompt is allowed to interpolate.
TEMPLATE_FIELDS = ("record_text", "labels")
