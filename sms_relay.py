#!/usr/bin/env python
"""CyClaw SMS Relay Sidecar — Twilio webhook receiver.

Receives inbound SMS via Twilio webhook, immediately ACKs with an empty TwiML
response (prevents the 15-second Twilio timeout from firing), then submits the
query asynchronously to the local CyClaw gateway and delivers the answer (or
current offline confirm prompt) as an outbound SMS.

Runtime flow
============
1. Twilio POSTs inbound SMS to /sms (HTTP).
2. sms_relay returns <Response/> immediately (200 OK, empty TwiML).
3. Background task hits CyClaw POST /query.
4a. If CyClaw returns needs_confirm=True, outbound SMS lists available options.
4b. If CyClaw returns an answer, outbound SMS sends the answer text.

Pending-confirm state machine
==============================
While a query is pending user confirmation the sender may reply:
  local    → re-submit with user_confirmed_online=False (offline best-effort)
  grok     → re-submit with user_confirmed_online=True, online_provider="grok"
  claude   → re-submit with user_confirmed_online=True, online_provider="claude"
  cancel   → clear pending state, send cancellation ack
  more     → resend last answer (after an answer has been delivered)

Important: in the default CyClaw config app.mode=offline and
grok.enabled=claude.enabled=false, so only the 'local' confirm path will
produce an actual answer. 'grok' / 'claude' will return an error from the
gateway until you set mode=hybrid and enable the respective provider.

Twilio setup
============
1. Buy or trial-activate an SMS-capable Twilio number.
2. In Twilio Console → Phone Numbers → Messaging → A Message Comes In:
   Webhook: https://YOUR-NGROK-DOMAIN/sms   Method: HTTP POST
3. Trial accounts can only message verified recipient numbers.

Environment variables (see sms_relay.env.example)
==================================================
  TWILIO_ACCOUNT_SID   – Twilio account SID (required)
  TWILIO_AUTH_TOKEN    – Twilio auth token (required)
  TWILIO_FROM_NUMBER   – Your Twilio SMS number, e.g. +14045550100 (required)
  CYCLAW_URL           – Base URL for CyClaw gateway (default: http://127.0.0.1:8787)
  SMS_RELAY_PORT       – Port this sidecar listens on (default: 8788)
  SMS_RELAY_HOST       – Bind host (default: 127.0.0.1; set 0.0.0.0 only behind ngrok)
  SMS_MAX_SMS_CHARS    – Truncate outbound messages longer than this (default: 1550)
  TWILIO_WEBHOOK_SECRET – Optional: shared secret for signature validation header
                          (not yet implemented — placeholder for future use)

Security notes
==============
- This sidecar intentionally does NOT validate the Twilio request signature.
  Add validate_twilio_request() (twilio.request_validator) if you expose this
  on a public IP rather than behind ngrok + loopback.
- Run behind an ngrok tunnel in local dev; never expose port 8788 directly.
- The sidecar only relays to CYCLAW_URL — it does not import gate.py.
"""

import asyncio
import logging
import os
import re
from contextlib import asynccontextmanager
from typing import Optional

import httpx
from fastapi import FastAPI, Form, BackgroundTasks, Request
from fastapi.responses import Response
from twilio.rest import Client as TwilioClient

# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------
ACCOUNT_SID: str = os.environ["TWILIO_ACCOUNT_SID"]
AUTH_TOKEN: str = os.environ["TWILIO_AUTH_TOKEN"]
FROM_NUMBER: str = os.environ["TWILIO_FROM_NUMBER"]
CYCLAW_URL: str = os.environ.get("CYCLAW_URL", "http://127.0.0.1:8787")
SMS_RELAY_PORT: int = int(os.environ.get("SMS_RELAY_PORT", "8788"))
SMS_RELAY_HOST: str = os.environ.get("SMS_RELAY_HOST", "127.0.0.1")
SMS_MAX_CHARS: int = int(os.environ.get("SMS_MAX_SMS_CHARS", "1550"))

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [sms_relay] %(levelname)s %(message)s",
)
logger = logging.getLogger("sms_relay")

# ---------------------------------------------------------------------------
# Twilio client (shared; thread-safe for reads, one SMS at a time is fine)
# ---------------------------------------------------------------------------
_twilio = TwilioClient(ACCOUNT_SID, AUTH_TOKEN)

# ---------------------------------------------------------------------------
# Minimal in-memory per-sender state
# {from_number: {"pending": bool, "last_query": str, "last_answer": str}}
# NOTE: single-process only — a multi-worker deploy would need Redis/sqlite.
# ---------------------------------------------------------------------------
_state: dict[str, dict] = {}

# ---------------------------------------------------------------------------
# Pending-confirm commands (normalised to lowercase, stripped)
# ---------------------------------------------------------------------------
_CONFIRM_COMMANDS = {"local", "grok", "claude", "cancel"}
_PROVIDER_MAP = {"grok": "grok", "claude": "claude", "local": None}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _truncate(text: str) -> str:
    """Hard-truncate and tag long answers so the SMS fits in carrier limits."""
    if len(text) <= SMS_MAX_CHARS:
        return text
    return text[:SMS_MAX_CHARS - 20] + "\n[truncated — reply 'more' for full]"


def _send_sms(to: str, body: str) -> None:
    """Blocking Twilio send — called inside asyncio.to_thread."""
    _twilio.messages.create(
        body=_truncate(body),
        from_=FROM_NUMBER,
        to=to,
    )
    logger.info("Outbound SMS sent to %s (%d chars)", to, len(body))


async def _send_sms_async(to: str, body: str) -> None:
    await asyncio.to_thread(_send_sms, to, body)


async def _query_cyclaw(
    query: str,
    user_confirmed_online: Optional[bool] = None,
    online_provider: Optional[str] = None,
) -> dict:
    """POST to CyClaw /query and return the parsed JSON dict."""
    payload: dict = {"query": query}
    if user_confirmed_online is not None:
        payload["user_confirmed_online"] = user_confirmed_online
    if online_provider:
        payload["online_provider"] = online_provider

    async with httpx.AsyncClient(base_url=CYCLAW_URL, timeout=360.0) as client:
        resp = await client.post("/query", json=payload)
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Background task: call CyClaw and SMS the result
# ---------------------------------------------------------------------------
async def _handle_query(
    from_number: str,
    query: str,
    user_confirmed_online: Optional[bool] = None,
    online_provider: Optional[str] = None,
) -> None:
    """Run asynchronously after the TwiML ACK has been returned to Twilio."""
    try:
        result = await _query_cyclaw(query, user_confirmed_online, online_provider)
    except httpx.HTTPStatusError as e:
        logger.error("CyClaw HTTP error: %s", e)
        await _send_sms_async(
            from_number,
            f"CyClaw error {e.response.status_code}: {e.response.text[:200]}",
        )
        return
    except Exception as e:  # noqa: BLE001
        logger.exception("Unexpected error querying CyClaw")
        await _send_sms_async(from_number, f"Relay error: {e}")
        return

    needs_confirm = result.get("needs_confirm", False)
    if needs_confirm:
        msg = result.get("confirm_message", "Vault miss.")
        _state[from_number] = {
            "pending": True,
            "last_query": query,
            "last_answer": "",
        }
        # Tailor the options based on what is actually enabled in this CyClaw instance.
        # The relay has no access to config.yaml, so it always lists all options
        # and lets the gateway return an appropriate error for disabled providers.
        reply = (
            f"{msg}\n"
            "Reply: local | grok | claude | cancel"
        )
        await _send_sms_async(from_number, reply)
    else:
        answer = result.get("answer", "[No answer]")
        _state[from_number] = {
            "pending": False,
            "last_query": query,
            "last_answer": answer,
        }
        model = result.get("model_used", "?")
        footer = f"\n\n— via CyClaw ({model})"
        await _send_sms_async(from_number, answer + footer)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "CyClaw SMS relay starting — port=%s, cyclaw=%s",
        SMS_RELAY_PORT,
        CYCLAW_URL,
    )
    yield
    logger.info("CyClaw SMS relay shutting down.")


app = FastAPI(
    title="CyClaw SMS Relay",
    description="Twilio webhook sidecar for CyClaw",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.post("/sms")
async def sms_webhook(
    background_tasks: BackgroundTasks,
    request: Request,
    From: str = Form(...),
    Body: str = Form(...),
) -> Response:
    """Twilio webhook endpoint.

    Returns empty TwiML immediately so Twilio does not time out while CyClaw
    generates its answer. The actual CyClaw call and outbound SMS are deferred
    to a background task.
    """
    incoming = Body.strip()
    from_number = From.strip()
    cmd = incoming.lower()

    logger.info("Inbound SMS from %s: %r", from_number, incoming[:80])

    sender_state = _state.get(from_number, {})

    # ----------------------------------------------------------------
    # 'more' — resend last answer regardless of pending state
    # ----------------------------------------------------------------
    if cmd == "more":
        last = sender_state.get("last_answer", "")
        if last:
            background_tasks.add_task(_send_sms_async, from_number, last)
        else:
            background_tasks.add_task(
                _send_sms_async, from_number, "No previous answer to resend."
            )
        return Response(content="<Response/>", media_type="application/xml")

    # ----------------------------------------------------------------
    # Pending-confirm commands
    # ----------------------------------------------------------------
    if sender_state.get("pending") and cmd in _CONFIRM_COMMANDS:
        last_query = sender_state.get("last_query", "")

        if cmd == "cancel":
            _state.pop(from_number, None)
            background_tasks.add_task(
                _send_sms_async, from_number, "Cancelled. Send a new question anytime."
            )
            return Response(content="<Response/>", media_type="application/xml")

        if cmd == "local":
            background_tasks.add_task(
                _handle_query, from_number, last_query,
                False,   # user_confirmed_online=False → offline best-effort
                None,
            )
        else:  # grok | claude
            background_tasks.add_task(
                _handle_query, from_number, last_query,
                True,
                _PROVIDER_MAP[cmd],
            )

        _state[from_number]["pending"] = False
        return Response(content="<Response/>", media_type="application/xml")

    # ----------------------------------------------------------------
    # New query
    # ----------------------------------------------------------------
    background_tasks.add_task(_handle_query, from_number, incoming)
    return Response(content="<Response/>", media_type="application/xml")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "cyclaw_url": CYCLAW_URL}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=SMS_RELAY_HOST, port=SMS_RELAY_PORT)
