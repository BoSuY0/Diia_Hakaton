
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
    Атомарний запис JSON-файлу з використанням .lock файлу.
    Це надійніше на Windows, ніж msvcrt, і уникає проблем з правами доступу
    при відкритті основного файлу.
    """
    import json
    import os
    import time
    import random

    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    
    max_retries = 100
    locked = False
    
    try:
        for i in range(max_retries):
            try:
                # Спробуємо створити лок-файл атомарно ("x" = create exclusive)
                # Якщо файл існує, вилетить FileExistsError
                with open(lock_path, "x"):
                    locked = True
                    break
            except FileExistsError:
                # Лок зайнятий, чекаємо
                time.sleep(random.uniform(0.05, 0.1))
                
                # Опціонально: перевірка на "мертвий" лок (якщо старіший за 5 сек)
                try:
                    if lock_path.exists():
                        stat = lock_path.stat()
                        if time.time() - stat.st_mtime > 5.0:
                            # Лок застарів, пробуємо видалити (обережно!)
                            try:
                                os.remove(lock_path)
                            except OSError:
                                pass
                except OSError:
                    pass
                continue
        
        if not locked:
            raise TimeoutError(f"Could not acquire lock for {path} after {max_retries} retries")

        # Тепер ми маємо ексклюзивний доступ.
        # Пишемо у тимчасовий файл і перейменовуємо (атомарна заміна)
        tmp_path = path.with_suffix(".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    finally:
        if locked:
            try:
                os.remove(lock_path)
            except OSError:
                pass
