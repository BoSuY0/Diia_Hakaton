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


def fill_docx_template(template_path: Path, field_values: Dict[str, str], output_path: Path) -> Path:
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
                # {{field}} та [[field]]
                placeholder_curly = f"{{{{{field_id}}}}}"
                placeholder_square = f"[[{field_id}]]"
                if placeholder_curly in text:
                    text = text.replace(placeholder_curly, value)
                if placeholder_square in text:
                    text = text.replace(placeholder_square, value)
            # Якщо плейсхолдер був порожній, після заміни можуть лишитися
            # "паспорт: ,", "РНОКПП:", "тел.: ," або "e-mail:" без значення.
            # Приберемо такі блоки:
            #   паспорт: , РНОКПП: 123  ->  РНОКПП: 123
            #   паспорт: , РНОКПП:      ->  "" (порожній рядок)
            #   тел.: , e-mail: test    ->  e-mail: test
            #   тел.: , e-mail:         ->  "" (порожній рядок)
            # Cleanup empty labels
            # Define labels to clean up if they are empty (followed by comma or end of line)
            labels_to_clean = ["паспорт", "РНОКПП", "тел.", "e-mail"]
            
            for label in labels_to_clean:
                # Escape label for regex
                safe_label = re.escape(label)
                # Case 1: Label followed by comma (and whitespace) -> remove
                text = re.sub(rf"{safe_label}:\s*,\s*", "", text)
                # Case 2: Label at end of string (or followed by whitespace only) -> remove
                text = re.sub(rf"{safe_label}:\s*$", "", text)
            
            # Clean up any remaining placeholders that weren't filled
            # (e.g. fields from other person types)
            text = re.sub(r"\{\{[^}]+\}\}", "", text)
            text = re.sub(r"\[\[[^]]+\]\]", "", text)
            
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
