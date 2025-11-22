from src.app.state import Conversation, ConversationStore


def test_conversation_defaults():
    c = Conversation("s1")
    assert c.messages == []
    assert c.tags == {}
    assert c.has_category_tool is False
    assert c.last_lang == "uk"


def test_conversation_store_creates_on_demand():
    store = ConversationStore()
    c1 = store.get("s1")
    assert c1.session_id == "s1"
    c2 = store.get("s1")
    assert c1 is c2
