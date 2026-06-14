"""Server-side sanitization for learner free-text (H-02).

Learner messages are untrusted. We sanitize them in the runtime/server BEFORE they reach the model:
trim, cap length, strip control characters, and defang any prompt-fence markers a learner might paste.

Crucially this adds NO visible wrapper or markers to the message — sanitization is invisible. Injection
defense rests on the user/system role boundary plus the agents' system-prompt guardrails, so no internal
scaffolding can leak into the conversation or be echoed back to the learner. (An earlier version wrapped
input in literal `<<<LEARNER_INPUT_*>>>` delimiters; the model began surfacing those markers to the
learner, so the wrapper was removed in favour of this quiet server-side clean-up.)
"""
from __future__ import annotations

import re

MAX_INPUT_CHARS = 2000
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")  # keep \n (\x0a) and \t (\x09)
_ZWSP = "​"


def sanitize_learner_input(text: str) -> str:
    """Clean untrusted learner text for safe use as a plain user-role message.

    Trims, caps length, removes control characters, and defangs angle-bracket prompt fences
    (e.g. `<<<...>>>`) by inserting a zero-width space so they can't act as injected markers.
    Returns clean, human-readable text — no wrapper, no visible markers.
    """
    if not text:
        return ""
    text = _CONTROL_CHARS.sub("", text)
    # Defang prompt-fence markers so pasted control tokens can't masquerade as system framing.
    text = text.replace("<<<", f"<{_ZWSP}<<").replace(">>>", f">>{_ZWSP}>")
    text = text.strip()
    if len(text) > MAX_INPUT_CHARS:
        text = text[:MAX_INPUT_CHARS].rstrip()
    return text
