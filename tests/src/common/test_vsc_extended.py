from backend.shared import vsc


def test_vsc_row_escapes():
    out = vsc.row("a|b", "c\nd")
    assert "\\|" in out
    assert "\\n" in out


def test_vsc_find_category_none():
    assert vsc.vsc_find_category({}) == "CATEGORY\nNONE"


def test_vsc_templates_formats():
    res = vsc.vsc_templates({"templates": [{"id": "t1", "name": "Name"}]})
    assert res.startswith("TEMPLATES")
    assert "t1|Name" in res


def test_vsc_entities_formats_required_flag():
    res = vsc.vsc_entities({"entities": [{"field": "f1", "label": "L", "type": "text", "required": True}]})
    assert "ENTITIES" in res
    assert "f1|L|text|1" in res


def test_vsc_upsert_result_can_build_flag():
    out = vsc.vsc_upsert_result({"field": "f", "status": "ok", "error": None, "state": "built", "can_build_contract": True})
    assert "FIELD_STATUS" in out
    assert "f|ok|-|built|1" in out


def test_vsc_summary_contains_fields():
    out = vsc.vsc_summary({
        "state": "s1",
        "can_build_contract": False,
        "fields": [{"field": "f1", "status": "ok", "error": None}],
    })
    assert "SUMMARY" in out
    assert "state|s1" in out
    assert "FIELDS" in out
    assert "f1|ok|-" in out


def test_vsc_built_formats():
    out = vsc.vsc_built({"filename": "f.docx", "file_path": "/tmp/f.docx", "mime": "mime"})
    assert "BUILT" in out
    assert "f.docx|/tmp/f.docx|mime" in out
