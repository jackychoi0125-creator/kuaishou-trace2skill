"""Fail-closed credential contract for real Harbor and optimizer calls.

The upstream credential must remain in an external proxy. This process and
the Harbor trial may receive only scoped proxy tokens. An administrator
attestation is deliberately stored outside the submission tree.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class ProxyCredentials:
    base_url: str
    token: str


def _attestation() -> dict:
    path = os.environ.get("TRACE2SKILL_SECURITY_ATTESTATION", "")
    if not path:
        raise RuntimeError("real model calls blocked: administrator security attestation is not configured")
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError("real model calls blocked: security attestation is unreadable or invalid") from exc
    rotation = data.get("credential_rotation") or {}
    proxy = data.get("proxy_isolation") or {}
    if rotation.get("status") != "confirmed" or not rotation.get("evidence_ref"):
        raise RuntimeError("real model calls blocked: old credential rotation lacks an auditable confirmation")
    if not proxy.get("verified") or not proxy.get("evidence_ref"):
        raise RuntimeError("real model calls blocked: external proxy isolation lacks an auditable confirmation")
    return data


def proxy_credentials(role: str) -> ProxyCredentials:
    if role not in {"optimizer", "target"}:
        raise ValueError(f"unsupported model role: {role}")
    # Explicit local-run mode is enabled only by the operator after they have
    # chosen to use the workstation's existing endpoint and credential.
    # Credentials are loaded by the local launcher and never placed in argv.
    if os.environ.get("TRACE2SKILL_DIRECT_LOCAL") == "1":
        base_url = os.environ.get(
            f"TRACE2SKILL_{role.upper()}_BASE_URL", os.environ.get("TRACE2SKILL_LOCAL_BASE_URL", "")
        ).strip()
        token = os.environ.get(
            f"TRACE2SKILL_{role.upper()}_API_KEY", os.environ.get("TRACE2SKILL_LOCAL_API_KEY", "")
        )
        if not base_url or not token:
            raise RuntimeError("direct local model settings are missing")
        parsed = urlparse(base_url)
        local_retry_proxy = (
            role == "target"
            and os.environ.get("TRACE2SKILL_LOCAL_RETRY_PROXY") == "1"
            and parsed.scheme == "http"
            and parsed.hostname == "host.docker.internal"
            and parsed.port is not None
        )
        if (not local_retry_proxy and parsed.scheme != "https") or not parsed.netloc or parsed.username or parsed.password:
            raise RuntimeError("direct local base URL must be HTTPS without embedded credentials")
        return ProxyCredentials(base_url=base_url.rstrip("/"), token=token)
    attestation = _attestation()
    prefix = f"TRACE2SKILL_{role.upper()}_PROXY"
    base_url = os.environ.get(f"{prefix}_BASE_URL", "").strip()
    token = os.environ.get(f"{prefix}_TOKEN", "")
    if not base_url or not token:
        raise RuntimeError(f"real model calls blocked: scoped {role} proxy settings are missing")
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise RuntimeError("proxy base URL must be HTTPS and must not contain embedded credentials")
    expected = ((attestation.get("proxy_isolation") or {}).get("base_urls") or {}).get(role)
    if expected != base_url:
        raise RuntimeError(f"real model calls blocked: {role} proxy URL does not match administrator attestation")
    return ProxyCredentials(base_url=base_url.rstrip("/"), token=token)


def assert_real_run_ready() -> None:
    """Validate both role-specific proxy routes without exposing tokens."""
    proxy_credentials("optimizer")
    proxy_credentials("target")
