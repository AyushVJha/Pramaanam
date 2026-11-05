"""What an agent is allowed to change in a report. (A1)

The rule behind every status (docs/CLAIM_CONTRACT.md): a green tick needs deterministic proof,
AI can raise a flag but never give a tick. This module turns that sentence into code, so an agent
step that misbehaves cannot break it, whatever the model says.

- An agent may never set VERIFIED.
- An agent may only set a status that asks for more care (NEEDS_REVIEW, UNSUPPORTED, CONTRADICTED,
  CANNOT_VERIFY).
- An agent may not touch a status that code already proved (MISQUOTE, NAME_MISMATCH,
  WRONG_PARAGRAPH, LOW_FIDELITY_SOURCE): those came from the number and the text, not from a model.
- NOT_FOUND_IN_CORPUS may become NEEDS_REVIEW (with candidates), never anything greener.
"""

AGENT_MAY_SET = frozenset({"NEEDS_REVIEW", "UNSUPPORTED", "CONTRADICTED", "CANNOT_VERIFY"})
AGENT_MAY_CHANGE = frozenset({"VERIFIED", "NEEDS_REVIEW", "NOT_FOUND_IN_CORPUS", "CANNOT_VERIFY"})


def allowed_change(current: str, proposed: str) -> bool:
    """True when an agent may move a report from `current` to `proposed`."""
    if proposed == current:
        return True  # no change is always safe
    return proposed in AGENT_MAY_SET and current in AGENT_MAY_CHANGE
