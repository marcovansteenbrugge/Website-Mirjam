"""Geheimen mogen nooit in een logregel of foutmelding staan."""

from __future__ import annotations

import logging

from app.redaction import REDACTED, RedactingLogFilter, Redactor


def test_letterlijk_geheim_wordt_weggepoetst() -> None:
    redactor = Redactor(["mijn-geheime-wachtwoord"])
    tekst = redactor.scrub("login mislukte met mijn-geheime-wachtwoord erin")
    assert "mijn-geheime-wachtwoord" not in tekst
    assert REDACTED in tekst


def test_jwt_wordt_weggepoetst() -> None:
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NSJ9.abcdefghijklmnop"
    assert jwt not in Redactor().scrub(f"token={jwt} einde")


def test_bearer_header_wordt_weggepoetst() -> None:
    tekst = Redactor().scrub("Authorization: Bearer abcdef1234567890")
    assert "abcdef1234567890" not in tekst


def test_wachtwoord_in_key_value_wordt_weggepoetst() -> None:
    tekst = Redactor().scrub('{"password": "hunter2000", "user": "marco"}')
    assert "hunter2000" not in tekst
    assert "marco" in tekst


def test_logfilter_poetst_de_boodschap(caplog) -> None:
    logger = logging.getLogger("test.redactie")
    logger.addFilter(RedactingLogFilter(Redactor(["supergeheim123"])))
    with caplog.at_level(logging.INFO, logger="test.redactie"):
        logger.info("inloggen met %s", "supergeheim123")
    assert "supergeheim123" not in caplog.text
