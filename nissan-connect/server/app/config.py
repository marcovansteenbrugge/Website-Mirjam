"""Configuratie uit environment variables.

Alle geheimen (APP_TOKEN, Nissan-inloggegevens) komen uitsluitend hier vandaan.
Ze worden nooit gelogd en nooit naar de frontend gestuurd.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Minimale lengte van APP_TOKEN. Dit endpoint kan een echte auto voorverwarmen,
#: dus een kort of leeg token is een weigering om te starten -- geen waarschuwing.
MIN_APP_TOKEN_LENGTH = 16


class Settings(BaseSettings):
    """Instellingen van de Nissan-Connect-backend."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Toegang tot deze app -------------------------------------------------
    app_token: str = Field(default="", description="Gedeeld bearer-token.")

    # --- Nissan-account -------------------------------------------------------
    nissan_username: str = Field(default="")
    nissan_password: str = Field(default="")
    nissan_region: str = Field(default="NL")

    # --- Modus ----------------------------------------------------------------
    mock: bool = Field(default=False)

    # --- Veiligheid / rate limiting ------------------------------------------
    poll_min_interval_seconds: int = Field(default=900, ge=0)

    # --- Job-afhandeling (geavanceerd) ---------------------------------------
    # Een verse meting duurt in de praktijk tientallen seconden tot twee minuten
    # (evcc geeft het na 2 minuten op). Blijf wel binnen het venster waarin de
    # frontend pollt.
    job_timeout_seconds: float = Field(default=110.0, gt=0)
    job_poll_interval_seconds: float = Field(default=10.0, gt=0)
    job_ttl_seconds: float = Field(default=600.0, gt=0)

    # --- Mock-gedrag (alleen relevant als MOCK=1) ----------------------------
    mock_failure_rate: float = Field(default=0.12, ge=0.0, le=1.0)

    @field_validator("app_token")
    @classmethod
    def _check_app_token(cls, value: str) -> str:
        if not value:
            raise ValueError(
                "APP_TOKEN is niet gezet. Zonder token zou iedereen op internet "
                "de auto kunnen voorverwarmen. Zet een lang, willekeurig token."
            )
        if len(value) < MIN_APP_TOKEN_LENGTH:
            raise ValueError(
                f"APP_TOKEN is te kort (minimaal {MIN_APP_TOKEN_LENGTH} tekens). "
                "Gebruik bijvoorbeeld: python -c \"import secrets;print(secrets.token_urlsafe(32))\""
            )
        return value

    @property
    def credentials_present(self) -> bool:
        """True als er Nissan-inloggegevens beschikbaar zijn."""
        return bool(self.nissan_username and self.nissan_password)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Geef de (gecachete) instellingen. Faalt hard bij een ontbrekend APP_TOKEN."""
    return Settings()


def reset_settings_cache() -> None:
    """Leeg de cache -- alleen bedoeld voor tests."""
    get_settings.cache_clear()
