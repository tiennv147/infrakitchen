from datetime import UTC, datetime, timedelta
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
from jwt.algorithms import RSAAlgorithm
import pytest

from application.service_instances import deploy_access
from application.service_instances.deploy_access import can_deploy, github_repository
from core.auth_providers import GithubOidcProviderConfig
from core.errors import AccessUnauthorized
from core.sso import github_oidc
from core.sso.github_oidc import GITHUB_OIDC_ISSUER, verify_github_oidc_token

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
KID = "test-key"


@pytest.fixture(autouse=True)
def github_keys(monkeypatch):
    jwk = RSAAlgorithm.to_jwk(KEY.public_key(), as_dict=True)
    jwk["kid"] = KID
    monkeypatch.setattr(github_oidc, "_jwks_cache", {"keys": [jwk], "at": time.monotonic()})


def _token(**overrides) -> str:
    now = datetime.now(UTC)
    claims = {
        "iss": GITHUB_OIDC_ISSUER,
        "aud": "infrakitchen",
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "repository": "Shop/Checkout-API",
        "repository_owner": "Shop",
    }
    claims.update(overrides)
    return jwt.encode(claims, KEY, algorithm="RS256", headers={"kid": KID})


class TestGithubOidc:
    @pytest.mark.asyncio
    async def test_valid_token(self):
        claims = await verify_github_oidc_token(GithubOidcProviderConfig(), _token())
        assert claims["repository"] == "Shop/Checkout-API"

    @pytest.mark.asyncio
    async def test_wrong_audience(self):
        with pytest.raises(AccessUnauthorized):
            await verify_github_oidc_token(GithubOidcProviderConfig(), _token(aud="someone-else"))

    @pytest.mark.asyncio
    async def test_expired(self):
        past = datetime.now(UTC) - timedelta(hours=1)
        with pytest.raises(AccessUnauthorized):
            await verify_github_oidc_token(GithubOidcProviderConfig(), _token(iat=past, exp=past))

    @pytest.mark.asyncio
    async def test_other_issuer(self):
        with pytest.raises(AccessUnauthorized):
            await verify_github_oidc_token(GithubOidcProviderConfig(), _token(iss="https://evil.example.com"))

    @pytest.mark.asyncio
    async def test_owner_allow_list(self):
        config = GithubOidcProviderConfig(allowed_owners=["other-org"])
        with pytest.raises(AccessUnauthorized, match="not allowed"):
            await verify_github_oidc_token(config, _token())
        assert await verify_github_oidc_token(GithubOidcProviderConfig(allowed_owners=["shop"]), _token())

    @pytest.mark.asyncio
    async def test_token_signed_by_another_key(self):
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        now = datetime.now(UTC)
        forged = jwt.encode(
            {
                "iss": GITHUB_OIDC_ISSUER,
                "aud": "infrakitchen",
                "iat": now,
                "exp": now + timedelta(minutes=5),
                "repository": "shop/checkout-api",
            },
            other,
            algorithm="RS256",
            headers={"kid": KID},
        )
        with pytest.raises(AccessUnauthorized):
            await verify_github_oidc_token(GithubOidcProviderConfig(), forged)

    @pytest.mark.asyncio
    async def test_unsigned_algorithm_is_refused(self):
        with pytest.raises(AccessUnauthorized):
            await verify_github_oidc_token(
                GithubOidcProviderConfig(), jwt.encode({"a": 1}, "k" * 32, algorithm="HS256", headers={"kid": KID})
            )


class TestDeployAccess:
    @pytest.mark.parametrize(
        ("url", "repo"),
        [
            ("https://github.com/Shop/Checkout-API", "shop/checkout-api"),
            ("https://github.com/shop/checkout-api.git", "shop/checkout-api"),
            ("https://github.com/shop/checkout-api/", "shop/checkout-api"),
            ("https://gitlab.com/shop/checkout-api", None),
            ("https://github.com/shop", None),
            (None, None),
        ],
    )
    def test_github_repository(self, url, repo):
        assert github_repository(url) == repo

    @pytest.mark.asyncio
    async def test_workflow_token_deploys_only_its_own_repository(self, monkeypatch):
        entity = AsyncMock(return_value=True)
        monkeypatch.setattr(deploy_access, "user_has_access_to_entity", entity)
        user = SimpleNamespace(provider="github_oidc", identifier="github-actions:shop/checkout-api")
        own = SimpleNamespace(id=uuid4(), repository_url="https://github.com/Shop/Checkout-API.git")
        other = SimpleNamespace(id=uuid4(), repository_url="https://github.com/shop/payments")
        assert await can_deploy(user, own) is True  # type: ignore[arg-type]
        assert await can_deploy(user, other) is False  # type: ignore[arg-type]
        entity.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_deploy_token_uses_its_casbin_policy(self, monkeypatch):
        monkeypatch.setattr(deploy_access, "user_has_access_to_entity", AsyncMock(return_value=True))
        user = SimpleNamespace(provider="ik_service_account", identifier="service-deployer:x")
        assert await can_deploy(user, SimpleNamespace(id=uuid4(), repository_url=None)) is True  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_others_need_edit_rights(self, monkeypatch):
        monkeypatch.setattr(deploy_access, "user_has_access_to_entity", AsyncMock(return_value=False))
        monkeypatch.setattr(deploy_access, "get_service_actions", AsyncMock(return_value=[]))
        user = SimpleNamespace(provider="github", identifier="dev@example.com")
        assert await can_deploy(user, SimpleNamespace(id=uuid4(), repository_url=None)) is False  # type: ignore[arg-type]
