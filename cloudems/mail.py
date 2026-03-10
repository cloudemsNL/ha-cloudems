# -*- coding: utf-8 -*-
"""CloudEMS — E-mail helper voor PDF-rapporten (v2.4.19).

Verstuurt maandelijkse of wekelijkse energierapporten via SMTP.
Ondersteunt Gmail App Passwords, Office 365 en generieke SMTP.
"""
from __future__ import annotations
import asyncio
import logging
import smtplib
import ssl
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

from .const import (
    CONF_MAIL_ENABLED, CONF_MAIL_HOST, CONF_MAIL_PORT,
    CONF_MAIL_USERNAME, CONF_MAIL_PASSWORD,
    CONF_MAIL_FROM, CONF_MAIL_TO, CONF_MAIL_USE_TLS,
    CONF_MAIL_MONTHLY, CONF_MAIL_WEEKLY,
    DEFAULT_MAIL_PORT, DEFAULT_MAIL_USE_TLS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class CloudEMSMailer:
    """Verzorgt SMTP-verbinding en het versturen van rapporten."""

    def __init__(self, hass: "HomeAssistant", config: dict) -> None:
        self._hass   = hass
        self._config = config

    @property
    def enabled(self) -> bool:
        return self._config.get(CONF_MAIL_ENABLED, False)

    @property
    def _smtp_host(self) -> str:
        return self._config.get(CONF_MAIL_HOST, "").strip()

    @property
    def _smtp_port(self) -> int:
        return int(self._config.get(CONF_MAIL_PORT, DEFAULT_MAIL_PORT))

    @property
    def _use_tls(self) -> bool:
        return bool(self._config.get(CONF_MAIL_USE_TLS, DEFAULT_MAIL_USE_TLS))

    @property
    def _username(self) -> str:
        return self._config.get(CONF_MAIL_USERNAME, "").strip()

    @property
    def _password(self) -> str:
        return self._config.get(CONF_MAIL_PASSWORD, "").strip()

    @property
    def _from_addr(self) -> str:
        return self._config.get(CONF_MAIL_FROM, "").strip() or self._username

    @property
    def _to_addrs(self) -> list[str]:
        raw = self._config.get(CONF_MAIL_TO, "")
        return [a.strip() for a in raw.split(",") if a.strip()]

    async def async_send_monthly_report(self, pdf_bytes: bytes, month_label: str) -> bool:
        """Verstuur het maandelijkse PDF-rapport. Geeft True terug bij succes."""
        if not self.enabled:
            return False
        subject = f"☀️ CloudEMS Maandrapport — {month_label}"
        body    = (
            f"Beste CloudEMS gebruiker,\n\n"
            f"Bijgevoegd vindt u het energierapport voor {month_label}.\n\n"
            f"Dit rapport is automatisch gegenereerd door CloudEMS.\n\n"
            f"— CloudEMS"
        )
        filename = f"cloudems-rapport-{month_label.lower().replace(' ', '-')}.pdf"
        return await self._async_send(subject, body, pdf_bytes, filename)

    async def async_send_weekly_summary(self, summary_text: str) -> bool:
        """Verstuur de wekelijkse tekst-samenvatting."""
        if not self.enabled:
            return False
        now = datetime.now(timezone.utc)
        subject = f"⚡ CloudEMS Weekoverzicht — week {now.isocalendar()[1]}"
        return await self._async_send(subject, summary_text, None, None)

    async def async_test_connection(self) -> tuple[bool, str]:
        """Test de SMTP-verbinding. Geeft (succes, bericht) terug."""
        try:
            await asyncio.get_event_loop().run_in_executor(None, self._test_smtp)
            return True, "Verbinding geslaagd"
        except Exception as err:
            return False, str(err)

    def _test_smtp(self) -> None:
        ctx = ssl.create_default_context() if self._use_tls else None
        with smtplib.SMTP(self._smtp_host, self._smtp_port, timeout=8) as smtp:
            if self._use_tls:
                smtp.starttls(context=ctx)
            if self._username and self._password:
                smtp.login(self._username, self._password)

    async def _async_send(
        self,
        subject: str,
        body: str,
        attachment: bytes | None,
        filename: str | None,
    ) -> bool:
        if not self._smtp_host or not self._to_addrs:
            _LOGGER.warning("CloudEMS mail: geen host of ontvanger geconfigureerd")
            return False
        try:
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._send_sync(subject, body, attachment, filename),
            )
            _LOGGER.info(
                "CloudEMS mail: '%s' verstuurd naar %s",
                subject, ", ".join(self._to_addrs),
            )
            return True
        except Exception as err:
            _LOGGER.error("CloudEMS mail: versturen mislukt: %s", err)
            return False

    def _send_sync(
        self,
        subject: str,
        body: str,
        attachment: bytes | None,
        filename: str | None,
    ) -> None:
        msg = MIMEMultipart()
        msg["From"]    = self._from_addr
        msg["To"]      = ", ".join(self._to_addrs)
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        if attachment and filename:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment)
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f'attachment; filename="{filename}"',
            )
            msg.attach(part)

        ctx = ssl.create_default_context() if self._use_tls else None
        with smtplib.SMTP(self._smtp_host, self._smtp_port, timeout=15) as smtp:
            if self._use_tls:
                smtp.starttls(context=ctx)
            if self._username and self._password:
                smtp.login(self._username, self._password)
            smtp.sendmail(self._from_addr, self._to_addrs, msg.as_string())
