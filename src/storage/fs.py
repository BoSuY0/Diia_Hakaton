from __future__ import annotations

from pathlib import Path
from typing import Any

from src.common.config import settings


def ensure_directories() -> None:
    # Корінь
    settings.documents_root.mkdir(parents=True, exist_ok=True)

    # Meta-data
    settings.meta_root.mkdir(parents=True, exist_ok=True)
    settings.meta_categories_root.mkdir(parents=True, exist_ok=True)
    settings.meta_users_root.mkdir(parents=True, exist_ok=True)
    # user meta subdirs: documents + sessions
    settings.meta_users_documents_root.mkdir(parents=True, exist_ok=True)
    settings.sessions_root.mkdir(parents=True, exist_ok=True)

    # Документи
    settings.documents_files_root.mkdir(parents=True, exist_ok=True)
    settings.default_documents_root.mkdir(parents=True, exist_ok=True)

    settings.filled_documents_root.mkdir(parents=True, exist_ok=True)


def session_answers_path(session_id: str) -> Path:
    return settings.sessions_root / f"session_{session_id}.json"


def output_document_path(template_id: str, session_id: str, ext: str = "docx") -> Path:
    filename = f"{template_id}_{session_id}.{ext}"
    return settings.output_root / filename


def read_json(path: Path) -> Any:
    import json

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    """
    Атомарний запис JSON-файлу:
    - пишемо у тимчасовий файл у тій самій директорії;
    - fsync;
    - os.replace поверх цільового шляху.

    Це мінімізує ризик гонок і частково записаних файлів при
    конкурентних оновленнях сесій.
    """
    import json
    import os
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=path.name,
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        except OSError:
            # Якщо файл уже замінено/видалено — ігноруємо
            pass
