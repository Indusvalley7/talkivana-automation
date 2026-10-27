from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Decision(str, Enum):
    APPROVE_CONTENT = "approve_content"
    REVISE_CONTENT = "revise_content"
    APPROVE_VIDEO = "approve_video"
    RETRY_VOICE = "retry_voice"
    RETRY_SLIDES = "retry_slides"
    RETRY_VIDEO = "retry_video"
    RESUME_VIDEO = "resume_video"
    REJECT = "reject"
    IGNORE = "ignore"


@dataclass(frozen=True)
class ApprovalCommand:
    decision: Decision
    reason: str = ""


_COMMANDS = {
    "APPROVE CONTENT": Decision.APPROVE_CONTENT,
    "APPROVE VIDEO": Decision.APPROVE_VIDEO,
    "RETRY VOICE": Decision.RETRY_VOICE,
    "RETRY VISUALS": Decision.RETRY_SLIDES,
    "RETRY SLIDES": Decision.RETRY_SLIDES,
    "RETRY VIDEO": Decision.RETRY_VIDEO,
    "RESUME VIDEO": Decision.RESUME_VIDEO,
    "REJECT": Decision.REJECT,
}


def parse_approval_command(body: str) -> ApprovalCommand:
    non_empty = [line.strip() for line in body.splitlines() if line.strip()]
    first_line = non_empty[0] if non_empty else ""
    continuation = "\n".join(non_empty[1:])
    normalized = first_line.strip().strip("`*_ ")
    upper = normalized.upper()
    if upper in _COMMANDS:
        return ApprovalCommand(_COMMANDS[upper], continuation[:4000])
    for prefix, decision in (
        ("REVISE CONTENT:", Decision.REVISE_CONTENT),
        ("RETRY VOICE:", Decision.RETRY_VOICE),
        ("RETRY VISUALS:", Decision.RETRY_SLIDES),
        ("RETRY SLIDES:", Decision.RETRY_SLIDES),
        ("RETRY VIDEO:", Decision.RETRY_VIDEO),
        ("RESUME VIDEO:", Decision.RESUME_VIDEO),
        ("REJECT:", Decision.REJECT),
    ):
        if upper.startswith(prefix):
            first_reason = normalized.split(":", 1)[1].strip()
            reason = "\n".join(part for part in (first_reason, continuation) if part)
            return ApprovalCommand(decision, reason[:4000])
    for command, decision in (
        ("REVISE CONTENT", Decision.REVISE_CONTENT),
        ("RETRY VOICE", Decision.RETRY_VOICE),
        ("RETRY VISUALS", Decision.RETRY_SLIDES),
        ("RETRY SLIDES", Decision.RETRY_SLIDES),
        ("RETRY VIDEO", Decision.RETRY_VIDEO),
        ("RESUME VIDEO", Decision.RESUME_VIDEO),
        ("REJECT", Decision.REJECT),
    ):
        if upper == command and continuation:
            return ApprovalCommand(decision, continuation[:4000])
    return ApprovalCommand(Decision.IGNORE)


def is_authorized(sender_login: str, configured_login: str, repository_owner: str) -> bool:
    allowed = {configured_login.casefold(), repository_owner.casefold()}
    return bool(sender_login) and sender_login.casefold() in allowed and "change_me" not in allowed
