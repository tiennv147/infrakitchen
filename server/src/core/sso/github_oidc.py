"""Authenticate GitHub Actions workflows by their OIDC token; the repository claim becomes the user."""

import time
from typing import Any

import httpx
import jwt
from jwt.algorithms import RSAAlgorithm

from core.errors import AccessUnauthorized
from core.sso.service import SSOService
from core.users.model import UserDTO
from core.users.schema import UserCreateWithProvider

from ..auth_providers import GithubOidcProviderConfig

GITHUB_OIDC_ISSUER = "https://token.actions.githubusercontent.com"
GITHUB_OIDC_JWKS_URL = f"{GITHUB_OIDC_ISSUER}/.well-known/jwks"
GITHUB_OIDC_PROVIDER = "github_oidc"
GITHUB_ACTIONS_PREFIX = "github-actions:"
_JWKS_TTL = 600
_jwks_cache: dict[str, Any] = {"keys": [], "at": 0.0}


async def _signing_key(kid: str) -> Any:
    for refresh in (False, True):
        if refresh or time.monotonic() - _jwks_cache["at"] > _JWKS_TTL:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(GITHUB_OIDC_JWKS_URL)
            _jwks_cache["keys"] = response.json().get("keys", []) if response.status_code == 200 else []
            _jwks_cache["at"] = time.monotonic()
        jwk = next((k for k in _jwks_cache["keys"] if k.get("kid") == kid), None)
        if jwk is not None:
            return RSAAlgorithm.from_jwk(jwk)
    raise AccessUnauthorized("Unknown GitHub OIDC signing key")


def is_github_oidc_token(unverified_claims: dict[str, Any]) -> bool:
    return unverified_claims.get("iss") == GITHUB_OIDC_ISSUER


async def verify_github_oidc_token(config: GithubOidcProviderConfig, token: str) -> dict[str, Any]:
    header = jwt.get_unverified_header(token)
    if header.get("alg") != "RS256" or not header.get("kid"):
        raise AccessUnauthorized("GitHub OIDC tokens must be RS256 with a key id")
    key = await _signing_key(header["kid"])
    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            key=key,
            algorithms=["RS256"],
            audience=config.audience,
            issuer=GITHUB_OIDC_ISSUER,
            options={"require": ["exp", "iat", "iss", "aud", "repository"]},
        )
    except jwt.PyJWTError as error:
        raise AccessUnauthorized(f"Invalid GitHub OIDC token: {error}") from error
    owner = str(claims.get("repository_owner", "")).lower()
    if config.allowed_owners and owner not in {o.lower() for o in config.allowed_owners}:
        raise AccessUnauthorized(f"GitHub owner '{owner}' is not allowed")
    return claims


async def github_oidc_user(service: SSOService, token: str) -> UserDTO:
    providers = await service.auth_provider_service.get_all(filter={"auth_provider": GITHUB_OIDC_PROVIDER})
    if not providers or providers[0].enabled is False:
        raise AccessUnauthorized("GitHub OIDC authentication is not enabled")
    config = providers[0].configuration
    if not isinstance(config, GithubOidcProviderConfig):
        raise AccessUnauthorized("GitHub OIDC provider configuration is invalid")

    claims = await verify_github_oidc_token(config, token)
    repository = str(claims["repository"]).lower()
    # No roles are granted: this user can only deploy the service whose repository it is.
    return await service.user_service.create_user_if_not_exists(
        UserCreateWithProvider(
            identifier=f"{GITHUB_ACTIONS_PREFIX}{repository}",
            provider=GITHUB_OIDC_PROVIDER,
            display_name=f"GitHub Actions ({repository})",
        )
    )
