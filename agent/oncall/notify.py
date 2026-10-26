"""The one outbound channel an alert may use, and only when the owner enabled it.

The token is a separate bot token (`TELEGRAM_ALERT_BOT_TOKEN`), the chat id is the owner's, and the
body is a fixed template built from counters and timestamps. No user message, note passage, prompt or
answer can reach this function: it does not accept one. A send failure is logged by status code only;
the token and the URL are never logged.
"""

from __future__ import annotations

import logging

import httpx

from agent.oncall.alerts import AlertState, Observation, message
from agent.oncall.config import OnCallSettings

LOGGER = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def send(state: AlertState, observation: Observation, settings: OnCallSettings) -> bool:
    if not settings.telegram_ready:
        LOGGER.info("alert notification skipped: no alert bot configured")
        return False
    assert settings.telegram_token is not None
    text = message(state, observation)
    try:
        response = httpx.post(
            TELEGRAM_API.format(token=settings.telegram_token),
            json={"chat_id": settings.telegram_chat_id, "text": text, "disable_web_page_preview": True},
            timeout=10.0,
        )
    except httpx.HTTPError as error:
        LOGGER.warning("alert notification failed: %s", type(error).__name__)
        return False
    if response.status_code != 200:
        LOGGER.warning("alert notification rejected: HTTP %s", response.status_code)
        return False
    LOGGER.info("alert notification sent: %s %s", state.name, state.state)
    return True
