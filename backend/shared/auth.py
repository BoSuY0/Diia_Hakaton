"""Authentication and user ID resolution utilities."""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException

from backend.infra.config.settings import settings
from backend.shared.logging import get_logger

try:
    import jwt as jwt_lib  # noqa: N811
except ImportError:  # pragma: no cover - dependency is optional for header-only mode
    jwt_lib = None


logger = get_logger(__name__)


def _decode_bearer_token(token: str) -> tuple[str, dict]:
    """Decode a JWT bearer token and return (user_id, payload)."""
    if not jwt_lib or not settings.auth_jwt_secret:
        raise HTTPException(
            status_code=401,
            detail="Auth token provided but JWT decoding is not configured",
        )

    options = {"verify_aud": bool(settings.auth_jwt_audience)}
    try:
        payload = jwt_lib.decode(
            token,
            settings.auth_jwt_secret,
            algorithms=[settings.auth_jwt_algorithm],
            audience=settings.auth_jwt_audience,
            issuer=settings.auth_jwt_issuer,
            options=options,
        )
    except jwt_lib.PyJWTError as exc:
        logger.warning("Failed to decode auth token: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid auth token") from exc

    user_id = payload.get("sub") or payload.get("user_id") or payload.get("uid")
    if not user_id:
        raise HTTPException(status_code=401, detail="Auth token missing subject")
    return str(user_id), payload


def _extract_bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    if authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return authorization.strip() or None


def _map_user_id(raw_user_id: str) -> str:
    prefix = settings.auth_user_prefix or ""
    if raw_user_id.startswith(prefix):
        return raw_user_id
    return f"{prefix}{raw_user_id}" if prefix else raw_user_id


def resolve_user_id(
    x_user_id: Optional[str],
    authorization: Optional[str],
    allow_anonymous: bool = False,
) -> Optional[str]:
    """
    Returns a user_id from Authorization Bearer JWT (when configured) or X-User-ID header.
    - auth_mode=jwt: requires a valid bearer token; X-User-ID is ignored for external clients.
    - auth_mode=auto (default): prefer bearer token when present, otherwise fall back to X-User-ID.
    - auth_mode=header: always use X-User-ID.
    """
    mode = settings.auth_mode
    token = _extract_bearer_token(authorization)

    if mode == "jwt":
        # JWT-only: require a bearer token, ignore X-User-ID
        if token:
            raw_id, _payload = _decode_bearer_token(token)
            return _map_user_id(raw_id)
        if allow_anonymous:
            return None
        raise HTTPException(status_code=401, detail="Missing bearer token")

    if mode == "auto":
        if token:
            raw_id, _payload = _decode_bearer_token(token)
            return _map_user_id(raw_id)
        if x_user_id:
            return x_user_id
        if allow_anonymous:
            return None
        raise HTTPException(status_code=401, detail="Missing authentication headers")

    # header mode (dev/debug)
    if x_user_id:
        return x_user_id
    if allow_anonymous:
        return None
    raise HTTPException(status_code=401, detail="Missing X-User-ID")


def diia_profile_from_token(token: str) -> dict:
    """
    Витягує базовий профіль користувача з JWT.
    Поля залежать від того, що віддає Дія; мапимо кілька варіантів.
    """
    if not jwt_lib or not token:
        return {}
    try:
        payload = jwt_lib.decode(
            token,
            settings.auth_jwt_secret,
            algorithms=[settings.auth_jwt_algorithm],
            audience=settings.auth_jwt_audience,
            issuer=settings.auth_jwt_issuer,
            options={"verify_aud": bool(settings.auth_jwt_audience)},
        )
    except jwt_lib.PyJWTError:
        return {}

    def pick(*keys):
        for k in keys:
            val = payload.get(k)
            if val:
                return val
        return None

    return {
        "full_name": pick("name", "full_name", "given_name"),
        "tax_id": pick("drfo", "tax_id", "rnokpp", "edrpou"),
        "address": pick("address", "residence_address"),
        "phone": pick("phone", "phone_number"),
        "email": pick("email"),
        "raw": payload,
    }
