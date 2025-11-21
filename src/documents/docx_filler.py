from __future__ import annotations

from pathlib import Path
from typing import Dict
import re

from docx import Document  # type: ignore


def _iter_paragraphs(doc: Document):
    for p in doc.paragraphs:
        yield p
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    yield p


def fill_docx_template(
    template_path: Path,
    field_values: Dict[str, str],
    output_path: Path,
    *,
    keep_placeholders: bool = False,
) -> Path:
    if template_path.exists():
        # Розширюємо словник полів синонімами для деяких party-полів,
        # щоб підтримати існуючі плейсхолдери у DOCX:
        #   <role>.id_doc   -> <role>.passport
        #   <role>.id_code  -> <role>.rnokpp
        values: Dict[str, str] = dict(field_values)
        for key, val in list(values.items()):
            if key.endswith(".id_doc"):
                alias = key.replace(".id_doc", ".passport")
                values.setdefault(alias, val)
            if key.endswith(".id_code"):
                alias = key.replace(".id_code", ".rnokpp")
                values.setdefault(alias, val)

        doc = Document(str(template_path))
        for paragraph in _iter_paragraphs(doc):
            text = paragraph.text
            for field_id, value in values.items():
                # Підтримуємо два формати плейсхолдерів:
                # {{field}} та [[field]] (зі/без пропусків усередині)
                patterns = [
                    rf"{{{{\s*{re.escape(field_id)}\s*}}}}",
                    rf"\[\[\s*{re.escape(field_id)}\s*\]\]",
                ]
                for pattern in patterns:
                    text = re.sub(pattern, lambda _: value, text)

            if not keep_placeholders:
                # Якщо плейсхолдер був порожній, після заміни можуть лишитися
                # "паспорт: ,", "РНОКПП:", "тел.: ," або "e-mail:" без значення.
                # Приберемо такі блоки.
                labels_to_clean = ["паспорт", "РНОКПП", "тел.", "e-mail"]

                for label in labels_to_clean:
                    safe_label = re.escape(label)
                    text = re.sub(rf"{safe_label}:\s*,\s*", "", text)
                    text = re.sub(rf"{safe_label}:\s*$", "", text)

                # Clean up any remaining placeholders that weren't filled
                # (e.g. fields from other person types)
                text = re.sub(r"\{\{[^}]+\}\}", "", text)
                text = re.sub(r"\[\[[^]]]+\]\]", "", text)

                # Drop порожні дужки та зайві пробіли, що лишилися від плейсхолдерів
                text = re.sub(r"\s*\(\s*[_\-\.,]*\s*\)\s*", " ", text)
                text = re.sub(r"\s{2,}", " ", text).strip()

            paragraph.text = text
    else:
        # Fallback: simple document with fields
        doc = Document()
        doc.add_heading("Автоматично згенерований документ", level=1)
        for field_id, value in field_values.items():
            doc.add_paragraph(f"{field_id}: {value}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))
    return output_path
