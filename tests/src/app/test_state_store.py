"""Tests for conversation store."""
from backend.api.http.state import conversation_store


def test_conversation_store_returns_same_instance():
    """Test conversation store returns same instance."""
    conv1 = conversation_store.get("sess1")
    conv2 = conversation_store.get("sess1")
    assert conv1 is conv2
    conv1.tags["[T]"] = "value"
    assert conversation_store.get("sess1").tags["[T]"] == "value"


def test_conversation_store_isolated_between_sessions():
    """Test conversation store isolated between sessions."""
    a = conversation_store.get("a")
    b = conversation_store.get("b")
    a.tags["x"] = "1"
    assert "x" not in b.tags
