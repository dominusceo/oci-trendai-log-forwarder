"""Forward OCI Connector Hub log batches to TrendAI Vision One HTTP Event Collection."""

import base64
import io
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

import oci
import requests
from fdk import response
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)

TREND_HEC_URL = os.environ["TREND_HEC_URL"]
TREND_JWT_SECRET_OCID = os.environ["TREND_JWT_SECRET_OCID"]
CONNECT_TIMEOUT_SECONDS = float(os.getenv("CONNECT_TIMEOUT_SECONDS", "10"))
READ_TIMEOUT_SECONDS = float(os.getenv("READ_TIMEOUT_SECONDS", "30"))


def get_trend_jwt() -> str:
    """Read the TrendAI collector JWT from OCI Vault using the Function resource principal."""
    signer = oci.auth.signers.get_resource_principals_signer()
    secrets_client = oci.secrets.SecretsClient({}, signer=signer)
    bundle = secrets_client.get_secret_bundle(TREND_JWT_SECRET_OCID).data
    encoded_secret = bundle.secret_bundle_content.content
    return base64.b64decode(encoded_secret).decode("utf-8").strip()


def as_events(payload: Any) -> List[Dict[str, Any]]:
    """Accept Connector Hub batches and common single-event wrappers."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return payload["data"]
    if isinstance(payload, dict):
        return [payload]
    raise ValueError("The Connector Hub payload must be a JSON object or array")


def event_timestamp(event: Dict[str, Any]) -> str:
    """Select an OCI timestamp when available; otherwise mark the forwarding time."""
    for key in ("time", "timeCreated", "datetime", "timestamp"):
        value = event.get(key)
        if value:
            return str(value)
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """Keep the original OCI record while adding stable fields useful to a generic collector."""
    source = event.get("source") or event.get("logSourceName") or "oci"
    return {
        "timestamp": event_timestamp(event),
        "source": source,
        "vendor": "Oracle",
        "product": "Oracle Cloud Infrastructure",
        "event": event,
    }


def build_http_session() -> requests.Session:
    retries = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("POST",),
        raise_on_status=False,
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retries))
    return session


def forward_events(events: List[Dict[str, Any]]) -> int:
    if not TREND_HEC_URL.startswith("https://"):
        raise ValueError("TREND_HEC_URL must use HTTPS")

    trend_jwt = get_trend_jwt()
    payload = [normalize_event(event) for event in events]
    http_response = build_http_session().post(
        TREND_HEC_URL,
        headers={
            "Authorization": f"Bearer {trend_jwt}",
            "Content-Type": "application/json",
        },
        data=json.dumps(payload, separators=(",", ":")),
        timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
    )
    http_response.raise_for_status()
    return len(payload)


def handler(ctx, data: io.BytesIO = None):
    """OCI Functions entry point configured as the Connector Hub target."""
    try:
        raw_payload = data.getvalue().decode("utf-8") if data else "{}"
        events = as_events(json.loads(raw_payload))
        forwarded = forward_events(events)
        LOGGER.info("Forwarded %s OCI log events to TrendAI Vision One", forwarded)
        return response.Response(
            ctx,
            response_data=json.dumps({"forwarded": forwarded}),
            headers={"Content-Type": "application/json"},
            status_code=200,
        )
    except Exception:
        LOGGER.exception("Unable to forward OCI logs to TrendAI Vision One")
        raise
