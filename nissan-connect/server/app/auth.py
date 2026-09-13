"""Toegangscontrole op de app zelf.

Eén gedeeld token uit `APP_TOKEN`, meegestuurd als `Authorization: Bearer <token>`.
De vergelijking gebeurt met :func:`secrets.compare_digest`, zodat de responstijd
niets verraadt over het token.

Dit endpoint kan een echte auto laten voorverwarmen. Een ontbrekend of te kort
`APP_TOKEN` is daarom een reden om niet te starten -- zie :mod:`app.config`.
"""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import Settings, get_settings
from .errors import ApiError

#: `auto_error=False`: we willen onze eigen Nederlandse foutrespons, niet die van FastAPI.
_bearer_scheme = HTTPBearer(auto_error=False, description="APP_TOKEN")


def _settings_from(request: Request) -> Settings:
    """Pak de instellingen van de app-state, met een fallback op de globale."""
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        settings = get_settings()
    return settings


async def require_token(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> None:
    """FastAPI-dependency die een geldig bearer-token afdwingt."""
    settings = _settings_from(request)
    expected = settings.app_token

    if credentials is None or (credentials.scheme or "").lower() != "bearer":
        raise ApiError(
            "unauthorized",
            "Geen toegang — stuur je token mee als 'Authorization: Bearer <token>'.",
        )

    supplied = credentials.credentials or ""
    if not secrets.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")):
        raise ApiError("unauthorized", "Geen toegang — dit token klopt niet.")


#: Handige alias voor in de routedefinities.
RequireToken = Depends(require_token)
