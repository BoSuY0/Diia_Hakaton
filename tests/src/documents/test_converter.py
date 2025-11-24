from pathlib import Path

from backend.domain.documents.converter import convert_to_html


def test_convert_to_html_uses_mammoth(monkeypatch, tmp_path):
    # Create dummy docx file
    input_path = tmp_path / "doc.docx"
    input_path.write_bytes(b"dummy")

    class DummyResult:
        value = "<p>Hi</p>"

    called = {}

    def fake_convert(file_obj):
        called["called"] = True
        return DummyResult()

    monkeypatch.setattr("backend.domain.documents.converter.mammoth.convert_to_html", fake_convert)
    html = convert_to_html(input_path)
    assert called.get("called") is True
    assert "<html" in html.lower()
    assert "Hi" in html


def test_convert_to_html_missing_file(tmp_path):
    missing = tmp_path / "missing.docx"
    try:
        convert_to_html(missing)
        assert False, "expected FileNotFoundError"
    except FileNotFoundError:
        pass
