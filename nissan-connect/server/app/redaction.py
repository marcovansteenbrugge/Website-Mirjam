"""Hulpmiddelen om geheimen uit logregels en foutmeldingen te houden.

Wachtwoorden en tokens mogen nooit in een logbestand of in een HTTP-respons
terechtkomen -- ook niet via een toevallige exception-tekst.
"""

from __future__ import annotations

import logging
import re
from typing import Iterable

REDACTED = "***"

_TOKEN_PATTERNS: tuple[re.Pattern[str], ...] = (
    # JWT's (header.payload.signature)
    re.compile(r"\beyJ[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}\b"),
    # Bearer-headers
    re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._\-]{8,}"),
    # veelvoorkomende sleutel=waarde-vormen
    re.compile(
        r"(?i)\b(password|passwd|pwd|access_token|refresh_token|id_token|"
        r"code_verifier|client_secret|app_token|authorization)"
        r"(\"?\s*[:=]\s*\"?)([^\s,&\"'}]+)"
    ),
)


class Redactor:
    """Vervangt bekende geheimen en token-achtige strings door ``***``."""

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        self._secrets: list[str] = [s for s in secrets if s and len(s) >= 4]

    def add(self, secret: str | None) -> None:
        """Voeg een extra letterlijk geheim toe dat weggepoetst moet worden."""
        if secret and len(secret) >= 4 and secret not in self._secrets:
            self._secrets.append(secret)

    def scrub(self, text: str) -> str:
        """Geef `text` terug zonder herkenbare geheimen."""
        for secret in self._secrets:
            if secret in text:
                text = text.replace(secret, REDACTED)
        text = _TOKEN_PATTERNS[0].sub(REDACTED, text)
        text = _TOKEN_PATTERNS[1].sub(r"\1 " + REDACTED, text)
        text = _TOKEN_PATTERNS[2].sub(r"\1\2" + REDACTED, text)
        return text


class RedactingLogFilter(logging.Filter):
    """Logging-filter dat elke boodschap door een :class:`Redactor` haalt."""

    def __init__(self, redactor: Redactor) -> None:
        super().__init__()
        self._redactor = redactor

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        try:
            record.msg = self._redactor.scrub(str(record.getMessage()))
            record.args = ()
        except Exception:  # pragma: no cover - logging mag nooit crashen
            record.msg = "<logregel onderdrukt tijdens redactie>"
            record.args = ()
        return True


def install_redaction(redactor: Redactor, logger_names: Iterable[str]) -> None:
    """Hang het redactiefilter aan de opgegeven loggers."""
    log_filter = RedactingLogFilter(redactor)
    for name in logger_names:
        logging.getLogger(name).addFilter(log_filter)
