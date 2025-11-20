import pytest
import json
from src.categories.index import store, list_templates, list_entities, list_party_fields




def test_store_load(mock_categories_data):
    cat = store.get("test_cat")
    assert cat is not None
    assert cat.id == "test_cat"

def test_list_templates(mock_categories_data):
    tmpls = list_templates("test_cat")
    assert len(tmpls) == 1
    assert tmpls[0].id == "t1"

def test_list_entities(mock_categories_data):
    ents = list_entities("test_cat")
    assert len(ents) == 1
    assert ents[0].field == "cf1"

def test_list_party_fields(mock_categories_data):
    pfs = list_party_fields("test_cat", "individual")
    assert len(pfs) == 1
    assert pfs[0].field == "name"
