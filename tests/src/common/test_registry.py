import pytest
from src.common.registry import Registry

def test_registry_register_and_get():
    reg = Registry()
    
    class MyItem:
        pass
    
    item = MyItem()
    reg.register("item1", item)
    
    assert reg.get("item1") == item
    assert len(reg.list()) == 1

def test_registry_overwrite():
    reg = Registry()
    
    reg.register("item1", "value1")
    assert reg.get("item1") == "value1"
    
    reg.register("item1", "value2")
    assert reg.get("item1") == "value2"

def test_registry_not_found():
    reg = Registry()
    assert reg.get("non_existent") is None

def test_registry_clear():
    reg = Registry()
    reg.register("item1", "value1")
    reg.clear()
    assert len(reg.list()) == 0
    assert reg.get("item1") is None
