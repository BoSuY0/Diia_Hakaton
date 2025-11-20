from datetime import datetime, timedelta
import os
from pathlib import Path
import logging

from src.common.config import settings
from src.storage.fs import read_json
from src.sessions.models import SessionState

logger = logging.getLogger(__name__)

def clean_stale_sessions(max_age_hours: int = 24):
    """
    Видаляє сесії, які не оновлювалися більше max_age_hours годин
    і не перебувають у "важливому" стані (ready_to_sign, completed).
    """
    sessions_dir = settings.sessions_root
    if not sessions_dir.exists():
        logger.warning(f"Sessions directory not found: {sessions_dir}")
        return

    now = datetime.now()
    threshold = now - timedelta(hours=max_age_hours)
    
    deleted_count = 0
    errors_count = 0

    for file_path in sessions_dir.glob("*.json"):
        try:
            # Спроба прочитати JSON
            data = read_json(file_path)
            
            # Перевірка статусу
            state_val = data.get("state", "idle")
            # Якщо сесія важлива - пропускаємо
            if state_val in [SessionState.READY_TO_SIGN.value, SessionState.COMPLETED.value]:
                continue

            # Додатковий захист: якщо існує фінальний файл, не видаляємо сесію
            # (навіть якщо статус змінився на чернетку через редагування)
            final_doc_path = settings.filled_documents_root / f"contract_{data.get('session_id')}.docx"
            if final_doc_path.exists():
                continue

            # Перевірка часу оновлення
            updated_at_str = data.get("updated_at")
            if updated_at_str:
                updated_at = datetime.fromisoformat(updated_at_str)
            else:
                # Якщо поля немає, використовуємо час модифікації файлу
                mtime = file_path.stat().st_mtime
                updated_at = datetime.fromtimestamp(mtime)
            
            if updated_at < threshold:
                logger.info(f"Deleting stale session: {file_path.name} (last updated: {updated_at})")
                file_path.unlink()
                deleted_count += 1

        except Exception as e:
            logger.error(f"Error processing session file {file_path}: {e}")
            errors_count += 1

    logger.info(f"Cleanup finished. Deleted: {deleted_count}, Errors: {errors_count}")
