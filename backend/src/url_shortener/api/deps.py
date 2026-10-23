from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from url_shortener.core.database import get_session
from url_shortener.core.security import decode_access_token
from url_shortener.models.user import User
from url_shortener.services.auth import get_user_by_id


def get_token_from_header(authorization: str | None = Header(default=None)) -> str | None:
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1]


def get_current_user(
    token: str | None = Depends(get_token_from_header),
    session: Session = Depends(get_session),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_exception

    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise credentials_exception

    try:
        user_id = int(user_id_str)
    except (ValueError, TypeError):
        raise credentials_exception

    user = get_user_by_id(session, user_id)
    if user is None or not user.is_active:
        raise credentials_exception

    return user


def get_optional_current_user(
    token: str | None = Depends(get_token_from_header),
    session: Session = Depends(get_session),
) -> User | None:
    if not token:
        return None

    payload = decode_access_token(token)
    if payload is None:
        return None

    user_id_str = payload.get("sub")
    if not user_id_str:
        return None

    try:
        user_id = int(user_id_str)
    except (ValueError, TypeError):
        return None

    user = get_user_by_id(session, user_id)
    if user is None or not user.is_active:
        return None

    return user


import ipaddress
import logging

from url_shortener.core.config import get_settings

logger = logging.getLogger(__name__)


def _parse_trusted_networks(
    trusted_proxies: list[str],
) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for entry in trusted_proxies:
        cleaned = entry.strip()
        if not cleaned:
            continue
        try:
            networks.append(ipaddress.ip_network(cleaned, strict=False))
        except ValueError:
            logger.warning("Invalid trusted proxy configuration entry: %r", entry)
    return networks


def _is_ip_trusted(
    ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address,
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network],
) -> bool:
    return any(ip_obj in net for net in networks)


def get_client_ip(
    request: Request,
    trusted_proxies: list[str] | None = None,
) -> str:
    """Extract client IP safely from request or proxy headers according to trusted proxy policy."""
    if trusted_proxies is None:
        trusted_proxies = get_settings().trusted_proxies

    # 1. Determine connecting peer IP
    peer_raw = request.client.host if request.client else None
    if not peer_raw:
        return "127.0.0.1"

    peer_str = peer_raw.strip()
    try:
        peer_ip = ipaddress.ip_address(peer_str)
    except ValueError:
        return peer_str

    # If no trusted proxies are configured, peer IP is the only authoritative source
    if not trusted_proxies:
        return str(peer_ip)

    trusted_nets = _parse_trusted_networks(trusted_proxies)
    if not trusted_nets or not _is_ip_trusted(peer_ip, trusted_nets):
        # Connecting peer is not a trusted proxy; do NOT honor forwarding headers
        return str(peer_ip)

    # 2. Peer is a trusted proxy. Inspect X-Forwarded-For chain from right to left
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        for part in reversed(parts):
            try:
                candidate = ipaddress.ip_address(part)
            except ValueError:
                # Malformed IP in chain; treat as untrusted candidate
                return part
            if not _is_ip_trusted(candidate, trusted_nets):
                return str(candidate)
        if parts:
            return parts[0]

    # Fallback to X-Real-IP if present
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        real_ip_clean = real_ip.strip()
        try:
            candidate = ipaddress.ip_address(real_ip_clean)
            if not _is_ip_trusted(candidate, trusted_nets):
                return str(candidate)
        except ValueError:
            return real_ip_clean

    return str(peer_ip)
