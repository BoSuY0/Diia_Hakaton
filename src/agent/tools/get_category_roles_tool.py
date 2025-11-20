from typing import Any, Dict, List

from src.agent.tools.registry import tool
from src.categories.index import get_role_info, get_roles, store as category_store
from src.common.logging import get_logger

logger = get_logger(__name__)


def _category_ids() -> List[str]:
    try:
        return sorted(category_store.categories.keys())
    except Exception:
        return []


@tool(
    name="get_category_roles",
    description="Повертає список ролей та типів осіб для категорії договору з людино-читабельними назвами",
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
    }
)
def get_category_roles_tool(args: Dict[str, Any], context: Dict[str, Any]) -> Any:
    category_id = args["category_id"]
    logger.info("tool=get_category_roles category_id=%s", category_id)
    
    # Get category metadata
    from src.categories.index import store, _load_meta
    category = store.get(category_id)
    if not category:
        return {"ok": False, "error": f"Unknown category: {category_id}"}
    
    meta = _load_meta(category)
    roles_data = meta.get("roles", {})
    party_modules = meta.get("party_modules", {})
    
    # Build person type labels map
    person_type_labels = {}
    for pt_id, pt_data in party_modules.items():
        person_type_labels[pt_id] = pt_data.get("label", pt_id)
    
    # Build roles info with person type labels
    roles_info = {}
    for role_id, role_data in roles_data.items():
        allowed_types = role_data.get("allowed_person_types", [])
        # Convert person type IDs to {id, label} objects
        person_types_with_labels = [
            {"id": pt_id, "label": person_type_labels.get(pt_id, pt_id)}
            for pt_id in allowed_types
        ]
        
        roles_info[role_id] = {
            "label": role_data.get("label", role_id),
            "person_types": person_types_with_labels
        }
    
    return {
        "category_id": category_id,
        "roles": roles_info
    }
