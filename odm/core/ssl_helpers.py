from __future__ import annotations

import os
from pathlib import Path


_SSL_ERROR_MARKERS = (
    "CERTIFICATE_VERIFY_FAILED",
    "certificate verify failed",
    "unable to get local issuer certificate",
)


def ensure_ssl_certificates() -> None:
    existing = os.environ.get("SSL_CERT_FILE")
    if existing and Path(existing).exists():
        return

    try:
        import certifi
    except Exception:
        return

    cert_path = certifi.where()
    if not cert_path:
        return

    os.environ.setdefault("SSL_CERT_FILE", cert_path)
    os.environ.setdefault("REQUESTS_CA_BUNDLE", cert_path)
    os.environ.setdefault("CURL_CA_BUNDLE", cert_path)


def is_certificate_verify_error(exc: Exception) -> bool:
    message = str(exc)
    return any(marker in message for marker in _SSL_ERROR_MARKERS)
