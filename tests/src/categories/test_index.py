"""Tests for category index."""
from backend.domain.categories.index import (
    store,
    list_templates,
    list_entities,
    list_party_fields,
    get_party_schema,
)


def test_store_load(mock_categories_data):  # pylint: disable=unused-argument
    """Test store load."""
    cat = store.get("test_cat")
    assert cat is not None
    assert cat.id == "test_cat"

def test_list_templates(mock_categories_data):  # pylint: disable=unused-argument
    """Test list templates."""
    tmpls = list_templates("test_cat")
    assert len(tmpls) == 1
    assert tmpls[0].id == "t1"

def test_list_entities(mock_categories_data):  # pylint: disable=unused-argument
    """Test list entities."""
    ents = list_entities("test_cat")
    assert len(ents) == 1
    assert ents[0].field == "cf1"

def test_list_party_fields(mock_categories_data):  # pylint: disable=unused-argument
    """Test list party fields."""
    pfs = list_party_fields("test_cat", "individual")
    assert len(pfs) == 1
    assert pfs[0].field == "name"


def test_get_party_schema(mock_categories_data):  # pylint: disable=unused-argument
    """Test get party schema."""
    schema = get_party_schema("test_cat")
    assert schema["category_id"] == "test_cat"
    assert any(r["id"] == "lessor" for r in schema["roles"])
    assert any(pt["person_type"] == "individual" for pt in schema["person_types"])
    # Ensure fields are included for person types
    indiv = next(pt for pt in schema["person_types"] if pt["person_type"] == "individual")
    assert indiv["fields"]
