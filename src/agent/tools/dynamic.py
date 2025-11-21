from typing import Any, Dict, List

from src.agent.tools.base import BaseTool
from src.agent.tools.dynamic_templates import create_dynamic_contract_template
from src.agent.tools.registry import register_tool

@register_tool
class CreateDynamicContractTemplateTool(BaseTool):
    name = "create_dynamic_contract_template"
    alias = "cdct"
    description = "Creates a new dynamic contract template (DOCX+JSON) based on generated text and fields."
    parameters = {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Title of the contract"
            },
            "contract_text": {
                "type": "string",
                "description": "Full text of the contract with {{placeholders}}"
            },
            "fields_metadata": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string"},
                        "label": {"type": "string"},
                        "required": {"type": "boolean"},
                        "type": {"type": "string", "enum": ["text", "date", "number"]},
                        "party": {"type": "string", "enum": ["party_a", "party_b", "common"]}
                    },
                    "required": ["field", "label"]
                }
            },
            "roles": {
                "type": "object",
                "properties": {
                    "party_a": {"type": "string"},
                    "party_b": {"type": "string"}
                },
                "required": ["party_a", "party_b"]
            }
        },
        "required": ["title", "contract_text", "fields_metadata", "roles"]
    }

    def execute(self, args: Dict[str, Any], context: Dict[str, Any]) -> str:
        title = args.get("title")
        contract_text = args.get("contract_text")
        fields_metadata = args.get("fields_metadata")
        roles = args.get("roles")
        
        # Validation is handled by the type checker mostly, but good to be safe
        if not all([title, contract_text, fields_metadata, roles]):
             raise ValueError("Missing required arguments: title, contract_text, fields_metadata, roles")

        template_id = create_dynamic_contract_template(title, contract_text, fields_metadata, roles)
        return f"Template created: {template_id}. You MUST now call set_template(category_id='custom', template_id='{template_id}')."
