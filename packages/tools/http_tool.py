from __future__ import annotations

import ipaddress
import logging
import socket
import time
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field

from packages.tools.base import BaseRealTool
from packages.tools.contract import (
    StandardToolResult,
    ToolContract,
    ToolExecutionContext,
    ToolRiskLevel,
)

logger = logging.getLogger(__name__)


class SSRFSecurityViolationError(PermissionError):
    """Raised when an HTTP request targets a private, loopback, or metadata address."""
    pass


class ResponseTooLargeError(ValueError):
    """Raised when the response size exceeds the configured maximum allowed bytes."""
    pass


class SSRFGuard:
    """
    Strict SSRF and DNS protection engine for outgoing HTTP requests.
    Enforces IP verification, metadata blocking, and domain allowlists.
    """

    BLOCKED_HOSTNAMES = {
        "localhost",
        "metadata.google.internal",
        "instance-data",
        "metadata.aws",
    }

    BLOCKED_NETWORKS = [
        ipaddress.ip_network("0.0.0.0/8"),
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("100.64.0.0/10"),
        ipaddress.ip_network("127.0.0.0/8"),
        ipaddress.ip_network("169.254.0.0/16"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.0.0.0/24"),
        ipaddress.ip_network("192.0.2.0/24"),
        ipaddress.ip_network("192.168.0.0/16"),
        ipaddress.ip_network("198.18.0.0/15"),
        ipaddress.ip_network("198.51.100.0/24"),
        ipaddress.ip_network("203.0.113.0/24"),
        ipaddress.ip_network("224.0.0.0/4"),
        ipaddress.ip_network("240.0.0.0/4"),
        ipaddress.ip_network("255.255.255.255/32"),
        # IPv6
        ipaddress.ip_network("::1/128"),
        ipaddress.ip_network("::/128"),
        ipaddress.ip_network("fc00::/7"),
        ipaddress.ip_network("fe80::/10"),
    ]

    SENSITIVE_HEADERS = {
        "authorization",
        "proxy-authorization",
        "x-api-key",
        "api-key",
        "cookie",
        "set-cookie",
        "token",
        "x-auth-token",
    }

    @classmethod
    def validate_url(
        cls,
        url: str,
        allowed_domains: list[str] | None = None,
    ) -> str:
        """
        Validate URL scheme, host, DNS resolution, and destination IPs against SSRF rules.
        """
        if not url or not isinstance(url, str):
            raise ValueError("URL must be a non-empty string")

        parsed = urlparse(url.strip())
        if parsed.scheme.lower() not in ("http", "https"):
            raise ValueError(f"Unsupported URL scheme '{parsed.scheme}'. Only http and https are allowed.")

        hostname = (parsed.hostname or "").strip().lower()
        if not hostname:
            raise ValueError("URL missing valid hostname")

        # 1. Blocked hostname keywords
        if hostname in cls.BLOCKED_HOSTNAMES or hostname.endswith(".localhost") or hostname.endswith(".local") or hostname.endswith(".internal"):
            raise SSRFSecurityViolationError(f"Target hostname '{hostname}' is blocked by SSRF policy.")

        # 2. Check domain allowlist if configured
        if allowed_domains:
            domain_matched = False
            for allowed in allowed_domains:
                allowed_clean = allowed.strip().lower()
                if allowed_clean.startswith("*."):
                    suffix = allowed_clean[1:]  # e.g. .example.com
                    if hostname.endswith(suffix):
                        domain_matched = True
                        break
                elif hostname == allowed_clean:
                    domain_matched = True
                    break
            if not domain_matched:
                raise SSRFSecurityViolationError(
                    f"Destination domain '{hostname}' is not in the allowed destinations list."
                )

        # 3. Port check
        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
        if port not in (80, 443, 8080, 8443):
            # Restrict to standard web ports
            raise SSRFSecurityViolationError(f"Target port {port} is not permitted for outgoing requests.")

        # 4. DNS resolution and IP address verification
        try:
            # Check if hostname is already a raw IP literal
            raw_ip = ipaddress.ip_address(hostname)
            resolved_ips = [raw_ip]
        except ValueError:
            # Resolve DNS
            try:
                addr_info = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
                resolved_ips = [
                    ipaddress.ip_address(item[4][0])
                    for item in addr_info
                ]
            except socket.gaierror as exc:
                raise ValueError(f"Could not resolve hostname '{hostname}': {str(exc)}")

        if not resolved_ips:
            raise ValueError(f"No IP addresses resolved for hostname '{hostname}'")

        # 5. Verify every resolved IP
        for ip in resolved_ips:
            if ip.is_loopback:
                raise SSRFSecurityViolationError(f"Resolved IP {ip} is a loopback address.")
            if ip.is_unspecified:
                raise SSRFSecurityViolationError(f"Resolved IP {ip} is an unspecified address.")
            if ip.is_private:
                raise SSRFSecurityViolationError(f"Resolved IP {ip} is a private network address.")
            if ip.is_link_local:
                raise SSRFSecurityViolationError(f"Resolved IP {ip} is a link-local address.")
            if ip.is_multicast:
                raise SSRFSecurityViolationError(f"Resolved IP {ip} is a multicast address.")
            if ip.is_reserved:
                raise SSRFSecurityViolationError(f"Resolved IP {ip} is a reserved address.")

            # Check explicit subnets
            for blocked_net in cls.BLOCKED_NETWORKS:
                if ip in blocked_net:
                    raise SSRFSecurityViolationError(
                        f"Resolved IP {ip} falls inside blocked network range {blocked_net}."
                    )

        return url

    @classmethod
    def sanitize_headers(cls, headers: dict[str, Any]) -> dict[str, str]:
        """Mask sensitive authentication and cookie headers."""
        sanitized = {}
        for k, v in headers.items():
            k_lower = str(k).lower().strip()
            if k_lower in cls.SENSITIVE_HEADERS:
                sanitized[k] = "********"
            else:
                sanitized[k] = str(v)
        return sanitized


class HttpRequestInput(BaseModel):
    url: str = Field(description="Target URL to request (http or https)")
    method: str = Field(default="GET", description="HTTP method: GET, POST, PUT, PATCH, DELETE")
    headers: dict[str, str] = Field(default_factory=dict, description="Custom HTTP headers")
    params: dict[str, Any] = Field(default_factory=dict, description="URL query parameters")
    json_body: Any = Field(default=None, description="JSON body payload for POST/PUT/PATCH")
    text_body: str | None = Field(default=None, description="Raw text payload")
    timeout: float = Field(default=10.0, ge=1.0, le=30.0, description="Request timeout in seconds (1 to 30)")
    max_response_bytes: int = Field(default=1048576, ge=1024, le=10485760, description="Max response size in bytes (up to 10MB)")
    allowed_domains: list[str] | None = Field(default=None, description="Optional list of allowed domain names")


class HttpRequestTool(BaseRealTool):
    """
    SSRF-protected production HTTP request tool.
    Supports GET, POST, PUT, PATCH, DELETE with strict DNS validation,
    response size limits, redirect safety, and header sanitization.
    """

    ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}

    def __init__(self, client: httpx.Client | None = None):
        self._client = client

    @property
    def contract(self) -> ToolContract:
        return ToolContract(
            slug="http_request",
            name="HTTP Request Tool",
            version="1.0.0",
            description="Executes authenticated or public HTTP requests to external APIs with strict anti-SSRF protection.",
            risk_level=ToolRiskLevel.MEDIUM,
            requires_approval=False,
            input_schema=HttpRequestInput.model_json_schema(),
            output_schema={
                "type": "object",
                "properties": {
                    "status_code": {"type": "integer"},
                    "headers": {"type": "object"},
                    "data": {"type": "any"},
                    "latency_ms": {"type": "number"},
                },
            },
            required_permissions=[("execute", "tools:http_request")],
            default_timeout=10.0,
            max_timeout=30.0,
            supports_idempotency=True,
            rate_limit_per_minute=60,
        )

    def validate_parameters(self, parameters: dict[str, Any]) -> dict[str, Any]:
        parsed = HttpRequestInput(**parameters)
        method_clean = parsed.method.strip().upper()
        if method_clean not in self.ALLOWED_METHODS:
            raise ValueError(f"HTTP method '{parsed.method}' is not supported. Allowed: {sorted(self.ALLOWED_METHODS)}")
        return parsed.model_dump()

    def run(self, context: ToolExecutionContext, **parameters: Any) -> dict[str, Any]:
        url = parameters["url"]
        method = parameters.get("method", "GET").upper()
        headers = dict(parameters.get("headers") or {})
        params = parameters.get("params") or {}
        json_body = parameters.get("json_body")
        text_body = parameters.get("text_body")
        timeout = float(parameters.get("timeout") or 10.0)
        max_bytes = int(parameters.get("max_response_bytes") or 1048576)
        allowed_domains = parameters.get("allowed_domains")

        # 1. Validate initial URL against SSRF
        validated_url = SSRFGuard.validate_url(url, allowed_domains=allowed_domains)

        # 2. Execute safe request with manual redirect following to inspect intermediate URLs
        current_url = validated_url
        current_method = method
        max_redirects = 5
        redirect_count = 0

        # Build HTTP client if not injected
        client = self._client or httpx.Client(timeout=timeout)
        should_close = self._client is None

        start_time = time.perf_counter()
        try:
            while True:
                # Prepare request
                req_headers = dict(headers)
                req_body = None
                if json_body is not None:
                    req_headers["Content-Type"] = "application/json"
                    import json
                    req_body = json.dumps(json_body).encode("utf-8")
                elif text_body is not None:
                    req_body = text_body.encode("utf-8")

                request = client.build_request(
                    method=current_method,
                    url=current_url,
                    headers=req_headers,
                    params=params if redirect_count == 0 else None,
                    content=req_body,
                )

                response = client.send(request, stream=True)

                # Check for redirects (301, 302, 303, 307, 308)
                if response.is_redirect and "location" in response.headers:
                    redirect_count += 1
                    if redirect_count > max_redirects:
                        response.close()
                        raise ValueError(f"Too many redirects (exceeded max {max_redirects})")

                    location = response.headers["location"]
                    # Resolve relative redirect URL
                    next_url = str(response.url.join(location))
                    response.close()

                    # CRITICAL: Validate next redirect destination against SSRF!
                    validated_url = SSRFGuard.validate_url(next_url, allowed_domains=allowed_domains)

                    # RFC 7231: 303 forces GET, 301/302 typically switch to GET for POST
                    if response.status_code == 303 or (response.status_code in (301, 302) and current_method == "POST"):
                        current_method = "GET"
                        json_body = None
                        text_body = None

                    # Strip sensitive authentication and cookie headers on cross-origin or downgraded redirects
                    orig_parsed = urlparse(current_url)
                    next_parsed = urlparse(validated_url)
                    orig_port = orig_parsed.port or (443 if orig_parsed.scheme == "https" else 80)
                    next_port = next_parsed.port or (443 if next_parsed.scheme == "https" else 80)
                    is_cross_origin = (
                        orig_parsed.hostname != next_parsed.hostname
                        or orig_parsed.scheme != next_parsed.scheme
                        or orig_port != next_port
                    )
                    if is_cross_origin:
                        headers = {
                            k: v for k, v in headers.items()
                            if k.lower().strip() not in SSRFGuard.SENSITIVE_HEADERS
                        }

                    current_url = validated_url
                    continue

                # Read response body with size limit guard
                chunks: list[bytes] = []
                total_bytes = 0
                for chunk in response.iter_bytes(chunk_size=16384):
                    total_bytes += len(chunk)
                    if total_bytes > max_bytes:
                        response.close()
                        raise ResponseTooLargeError(
                            f"Response size exceeded configured maximum limit of {max_bytes} bytes"
                        )
                    chunks.append(chunk)

                raw_content = b"".join(chunks)
                content_type = response.headers.get("content-type", "").lower()

                parsed_data: Any = None
                if "application/json" in content_type:
                    try:
                        import json
                        parsed_data = json.loads(raw_content.decode("utf-8"))
                    except Exception:
                        parsed_data = raw_content.decode("utf-8", errors="replace")
                else:
                    parsed_data = raw_content.decode("utf-8", errors="replace")

                duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
                sanitized_resp_headers = SSRFGuard.sanitize_headers(dict(response.headers))

                return {
                    "status_code": response.status_code,
                    "is_success": 200 <= response.status_code < 300,
                    "headers": sanitized_resp_headers,
                    "data": parsed_data,
                    "content_length": len(raw_content),
                    "latency_ms": duration_ms,
                }
        finally:
            if should_close:
                client.close()
