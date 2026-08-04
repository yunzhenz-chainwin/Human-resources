from __future__ import annotations

from app.models import Candidate, User
from app.schemas.hr import CandidateRead


def mask_email(value: str | None) -> str | None:
    """Return a useful but non-contactable representation of an email address."""

    if not value:
        return None
    local, separator, domain = value.partition("@")
    if not separator or not domain:
        return "***"
    visible = local[:1]
    return f"{visible}***@{domain}"


def mask_phone(value: str | None) -> str | None:
    """Hide a phone number while retaining a short disambiguating suffix."""

    if not value:
        return None
    digits = "".join(character for character in value if character.isdigit())
    if not digits:
        return "***"
    visible_digits = min(3, len(digits))
    return f"{'*' * max(3, len(digits) - visible_digits)}{digits[-visible_digits:]}"


def candidate_read_for_user(candidate: Candidate, user: User) -> CandidateRead:
    """Serialize a candidate with the manager-facing privacy boundary applied.

    HR and recruiting administrators retain the existing complete response. A
    department manager gets only scoped recruiting data: contact details are
    masked and residence/location is omitted. Birth and street-address fields
    are intentionally absent from ``CandidateRead`` altogether.
    """

    result = CandidateRead.model_validate(candidate)
    if user.role != "manager":
        return result
    return result.model_copy(
        update={
            "email": mask_email(result.email),
            "phone": mask_phone(result.phone),
            "city": None,
        }
    )
