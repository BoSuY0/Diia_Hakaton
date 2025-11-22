import json
import shutil
from pathlib import Path

import pytest
from docx import Document

from src.documents.builder import build_contract
from src.sessions.store import get_or_create_session, save_session
from src.sessions.models import FieldState


@pytest.mark.asyncio
async def test_build_real_estate_contract_full(mock_settings, monkeypatch):
    """
    Use real lease_real_estate metadata/template and ensure values are injected.
    """
    # Copy real metadata into temp workspace
    repo_root = Path(__file__).resolve().parents[3]
    meta_src = repo_root / "assets" / "meta_data" / "meta_data_categories_documents" / "lease_real_estate.json"
    meta_dst_dir = mock_settings.meta_categories_root
    meta_dst_dir.mkdir(parents=True, exist_ok=True)
    meta_dst = meta_dst_dir / "lease_real_estate.json"
    meta_dst.write_text(meta_src.read_text(encoding="utf-8"), encoding="utf-8")

    # Write categories_index.json for store
    index_path = meta_dst_dir / "categories_index.json"
    index_data = {"categories": [{"id": "lease_real_estate", "label": "Оренда нерухомого майна"}]}
    index_path.write_text(json.dumps(index_data), encoding="utf-8")

    # Patch categories index path and reload store
    monkeypatch.setattr("src.categories.index._CATEGORIES_PATH", index_path)
    from src.categories import index as cat_index

    cat_index.store._categories = {}
    cat_index.store.load()

    # Copy real DOCX template into temp workspace
    tmpl_src = repo_root / "assets" / "documents_files" / "default_documents_files" / "lease_real_estate.docx"
    tmpl_dst_dir = mock_settings.default_documents_root / "lease_real_estate"
    tmpl_dst_dir.mkdir(parents=True, exist_ok=True)
    tmpl_dst = tmpl_dst_dir / "lease_real_estate.docx"
    shutil.copy(tmpl_src, tmpl_dst)

    # Prepare session with required data
    sid = "lease_real_full"
    s = get_or_create_session(sid)
    s.category_id = "lease_real_estate"
    s.template_id = "lease_flat"
    s.party_types = {"lessor": "individual", "lessee": "individual"}

    # Required contract fields (per metadata)
    contract_values = {
        "document_number": "1001",
        "city": "Київ",
        "contract_date": "22 листопада 2025",
        "purpose": "проживання",
        "object_address": "м. Стрий, вул. Шевченка, 32",
        "start_date": "24.11.2025",
        "end_date": "23.12.2025",
        "total_area_sqm": "52",
        "area_sqm": "45",
        "notice_period_days": "за 3 дні",
        "repair_notice_days": "заборонено",
        "improvement_consent_type": "не можна",
        "lock_change_notice": "з повідомленням",
        "sublease_consent_type": "за згодою",
        "act_signing_period": "протягом 3 днів",
        "term_change_consent": "не можна",
        "rent_price_month": "1400 грн",
        "first_payment_date": "24.11.2025",
        "payment_form": "безготівка",
        "payment_due_day": "1-го числа",
        "penalty_rate": "0,2%/день",
        "payment_delay_days": "5 днів",
        "premises_return_deadline": "протягом 1 дня",
    }
    for key, val in contract_values.items():
        s.contract_fields[key] = FieldState(status="ok")
        s.all_data[key] = {"current": val}

    # Party fields (individual module requires name+address)
    s.party_fields = {
        "lessor": {
            "name": FieldState(status="ok"),
            "address": FieldState(status="ok"),
        },
        "lessee": {
            "name": FieldState(status="ok"),
            "address": FieldState(status="ok"),
        },
    }
    s.all_data["lessor.name"] = {"current": "Орендодавець ПІБ"}
    s.all_data["lessor.address"] = {"current": "Київ, вул. Лесі Українки, 1"}
    s.all_data["lessee.name"] = {"current": "Орендар ПІБ"}
    s.all_data["lessee.address"] = {"current": "Львів, вул. Городоцька, 2"}

    save_session(s)

    result = await build_contract(sid, "lease_flat")
    built = Document(result["file_path"])
    full_text = "\n".join(p.text for p in built.paragraphs)

    # Spot-check a few injected values from both contract and party fields
    assert "ДОГОВІР ОРЕНДИ НЕРУХОМОГО МАЙНА" in full_text
    assert "Орендодавець ПІБ" in full_text
    assert "Орендар ПІБ" in full_text
    assert "1400 грн" in full_text
    assert "м. Стрий, вул. Шевченка, 32" in full_text
