from typing import Any, Dict, List, Optional

from src.agent.tools.registry import tool
from src.categories.index import Entity, list_entities, list_templates, store as category_store
from src.common.logging import get_logger
from src.common.vsc import vsc_entities

logger = get_logger(__name__)


@tool(
    name="get_category_entities",
    description="Повертає список полів (entities), які потрібно заповнити для категорії.",
    parameters={
        "type": "object",
        "properties": {
            "category_id": {
                "type": "string",
                "minLength": 1,
            }
        },
        "required": ["category_id"],
        "additionalProperties": False,
    },
    format_result_func=vsc_entities
)
def get_category_entities_tool(args: Dict[str, Any], context: Dict[str, Any]) -> Any:
    category_id = args["category_id"]
    logger.info("tool=get_category_entities category_id=%s", category_id)
    
    try:
        entities: List[Entity] = list_entities(category_id)
    except ValueError:
        # Fallback logic
        fixed_category_id: Optional[str] = None
        for category in category_store.categories.values():
            for t in list_templates(category.id):
                if t.id == category_id:
                    fixed_category_id = category.id
                    break
            if fixed_category_id:
                break
        if not fixed_category_id:
            raise
        logger.info(
            "tool=get_category_entities fix_template_id template_id=%s -> category_id=%s",
            category_id,
            fixed_category_id,
        )
        entities = list_entities(fixed_category_id)
        category_id = fixed_category_id

    return {
        "category_id": category_id,
        "entities": [
            {
                "field": e.field,
                "label": e.label,
                "type": e.type,
                "required": e.required,
            }
            for e in entities
        ],
    }
