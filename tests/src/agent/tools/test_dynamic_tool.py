import pytest
from unittest.mock import patch

from src.agent.tools.dynamic import CreateDynamicContractTemplateTool


def test_create_dynamic_contract_template_requires_args():
    tool = CreateDynamicContractTemplateTool()
    with pytest.raises(ValueError):
        tool.execute({}, {})


def test_create_dynamic_contract_template_invokes_builder():
    tool = CreateDynamicContractTemplateTool()
    with patch("src.agent.tools.dynamic.create_dynamic_contract_template", lambda *args, **kwargs: "dyn_id"):
        res = tool.execute(
            {
                "title": "T",
                "contract_text": "Text {{field}}",
                "fields_metadata": [{"field": "f1", "label": "F1", "required": True, "type": "text", "party": "common"}],
                "roles": {"party_a": "A", "party_b": "B"},
            },
            {},
        )
        assert "dyn_id" in res
        assert "Template created" in res
