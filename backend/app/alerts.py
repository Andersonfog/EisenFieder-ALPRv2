"""Owner text alerts for watchlist hits.

When a camera reports a vehicle whose plate is on the active watchlist (a banned
customer, a BOLO, etc.), the owner gets a text message.

* If Twilio is installed and configured (env: TWILIO_ACCOUNT_SID,
  TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER, OWNER_PHONE), a real SMS is sent.
* Otherwise the alert is logged to the server (so it works in the demo without
  any SMS account), and you can add Twilio later with zero code changes.

Sending is best-effort and never blocks or breaks event ingest.
"""

from __future__ import annotations

import logging

from .config import Settings

logger = logging.getLogger("eisenfieder.surveillance.alerts")


class AlertDispatcher:
    def __init__(self, settings: Settings) -> None:
        self.enabled = settings.alerts_enabled
        self.owner_phone = settings.owner_phone
        self.sid = settings.twilio_account_sid
        self.token = settings.twilio_auth_token
        self.from_number = settings.twilio_from_number
        self._client = None
        if self._twilio_ready():
            try:
                from twilio.rest import Client

                self._client = Client(self.sid, self.token)
                logger.info("Alerts: Twilio SMS enabled (to %s)", self.owner_phone)
            except Exception as exc:  # missing package or bad creds
                logger.warning("Alerts: Twilio unavailable (%s); will log instead.", exc)

    def _twilio_ready(self) -> bool:
        return bool(self.sid and self.token and self.from_number and self.owner_phone)

    @staticmethod
    def _describe(make, model, color, vtype) -> str:
        parts = [p for p in [color, make, model] if p]
        desc = " ".join(parts) if parts else (vtype or "vehicle")
        if vtype and parts:
            desc += f" ({vtype})"
        return desc

    def send_watchlist_hit(self, *, plate, reason, camera_id, captured_at,
                           make=None, model=None, color=None, vehicle_type=None) -> None:
        if not self.enabled:
            return
        vehicle = self._describe(make, model, color, vehicle_type)
        body = (
            f"EisenFieder ALERT: watchlisted plate {plate} "
            f"({reason or 'flagged'}) seen at {camera_id}. {vehicle}. {captured_at}"
        )
        try:
            if self._client is not None:
                self._client.messages.create(
                    to=self.owner_phone, from_=self.from_number, body=body
                )
                logger.info("Alert SMS sent to owner for plate %s", plate)
            else:
                # Console fallback — visible in the server log; wire Twilio for real SMS.
                logger.warning("ALERT (would text %s): %s",
                               self.owner_phone or "OWNER", body)
        except Exception as exc:  # never let an alert break ingest
            logger.warning("Alert dispatch failed for plate %s: %s", plate, exc)


_dispatcher: AlertDispatcher | None = None


def get_alert_dispatcher(settings: Settings) -> AlertDispatcher:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = AlertDispatcher(settings)
    return _dispatcher
