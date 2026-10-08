"""Per-recipient validation.

The request as a whole is validated by Pydantic (`JobCreate`). Individual recipients are
validated here so that one bad row is reported back instead of rejecting the entire batch.
"""

from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from app.schemas import RecipientIn


@dataclass
class RecipientResult:
    row_index: int
    raw: dict
    recipient: RecipientIn | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return self.recipient is not None and not self.errors


def _format_errors(exc: ValidationError) -> list[str]:
    messages = []
    for err in exc.errors():
        location = ".".join(str(part) for part in err["loc"]) or "recipient"
        messages.append(f"{location}: {err['msg']}")
    return messages


def validate_recipients(recipients: list[Any]) -> list[RecipientResult]:
    results: list[RecipientResult] = []
    seen_emails: dict[str, int] = {}

    for index, raw in enumerate(recipients):
        if not isinstance(raw, dict):
            results.append(RecipientResult(index, {"value": raw}, errors=["recipient must be an object"]))
            continue

        result = RecipientResult(index, raw)
        try:
            result.recipient = RecipientIn.model_validate(raw)
        except ValidationError as exc:
            result.errors = _format_errors(exc)
            results.append(result)
            continue

        email = result.recipient.email
        if email:
            key = email.lower()
            if key in seen_emails:
                result.errors.append(f"email: duplicate of recipient at index {seen_emails[key]}")
            else:
                seen_emails[key] = index
        results.append(result)

    return results
