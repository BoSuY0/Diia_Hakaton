"""Tests for shared registry."""
from backend.shared.registry import Registry


def test_registry_register_and_get():
    """Test registry register and get."""
    reg = Registry()

    class MyItem:  # pylint: disable=too-few-public-methods
        """Test item class."""

    item = MyItem()
    reg.register("item1", item)

    assert reg.get("item1") == item
    assert len(reg.list()) == 1


def test_registry_overwrite():
    """Test registry overwrite."""
    reg = Registry()

    reg.register("item1", "value1")
    assert reg.get("item1") == "value1"

    reg.register("item1", "value2")
    assert reg.get("item1") == "value2"


def test_registry_not_found():
    """Test registry not found."""
    reg = Registry()
    assert reg.get("non_existent") is None

def test_registry_clear():
    """Test registry clear."""
    reg = Registry()
    reg.register("item1", "value1")
    reg.clear()
    assert len(reg.list()) == 0
    assert reg.get("item1") is None


def test_registry_list_returns_copy():
    """Test registry list returns copy."""
    reg = Registry()
    reg.register("item1", {"a": 1})
    listed = reg.list()
    listed["item1"]["a"] = 2
    # Original should remain unchanged
    assert reg.get("item1") == {"a": 1}
