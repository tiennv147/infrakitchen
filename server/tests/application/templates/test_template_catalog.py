from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from application.templates.schema import TemplateConfig


class TestOfferingCatalogConfig:
    def test_templates_are_not_claimable_by_default(self):
        config = TemplateConfig()
        assert config.claimable is False
        assert config.binding_outputs == []

    def test_existing_configuration_without_catalog_fields_still_parses(self):
        config = TemplateConfig.model_validate({"naming_convention": "redis-{service_name}"})
        assert config.claimable is False

    def test_binding_outputs_must_be_identifiers(self):
        with pytest.raises(ValidationError, match="Invalid binding output name"):
            TemplateConfig(binding_outputs=["endpoint", "bad-name"])

    def test_binding_outputs_must_be_unique(self):
        with pytest.raises(ValidationError, match="unique"):
            TemplateConfig(binding_outputs=["endpoint", "endpoint"])


class TestClaimableQuery:
    @pytest.mark.asyncio
    async def test_query_claimable_delegates_to_crud(self, mock_template_service, mock_template_crud):
        mock_template_crud.get_claimable = AsyncMock(return_value=["t"])

        assert await mock_template_service.query_claimable(fields={"id": None}) == ["t"]
        mock_template_crud.get_claimable.assert_awaited_once_with(fields={"id": None})
