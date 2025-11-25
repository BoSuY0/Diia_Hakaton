from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import logging

from backend.infra.config.settings import settings
from backend.infra.storage.fs import read_json
from backend.domain.sessions.models import SessionState
from backend.domain.sessions.ttl import ttl_hours_for_state

logger = logging.getLogger(__name__)


def _is_filesystem_backend() -> bool:
    return getattr(settings, "session_backend", "redis").lower() == "fs"

def clean_stale_sessions(max_age_hours: int | None = None):
    """
    Видаляє сесії, які не оновлювалися більше max_age_hours годин
    і не перебувають у "важливому" стані (ready_to_sign, completed).
    """
    if not _is_filesystem_backend():
        logger.debug("Non-filesystem backend detected; skipping clean_stale_sessions")
        return

    sessions_dir = settings.sessions_root
    if not sessions_dir.exists():
        logger.warning(f"Sessions directory not found: {sessions_dir}")
        return

    now = datetime.now(timezone.utc)
    deleted_count = 0
    errors_count = 0

    default_threshold_hours = max_age_hours if max_age_hours is not None else settings.draft_ttl_hours

    for file_path in sessions_dir.glob("*.json"):
        try:
            # Спроба прочитати JSON
            data = read_json(file_path)
            
            # Перевірка статусу
            state_val = data.get("state", "idle")
            try:
                state_enum = SessionState(state_val)
            except Exception:
                state_enum = SessionState.IDLE

            ttl_hours = ttl_hours_for_state(state_enum)
            threshold_hours = ttl_hours if max_age_hours is None else min(ttl_hours, default_threshold_hours)
            threshold = now - timedelta(hours=threshold_hours)

            # Додатковий захист: якщо існує фінальний файл, не видаляємо сесію
            # (навіть якщо статус змінився на чернетку через редагування)
            final_doc_path = settings.filled_documents_root / f"contract_{data.get('session_id')}.docx"
            if state_enum == SessionState.COMPLETED and final_doc_path.exists():
                continue

            # Перевірка часу оновлення
            updated_at_str = data.get("updated_at")
            if updated_at_str:
                updated_at = datetime.fromisoformat(updated_at_str)
                if updated_at.tzinfo is None:
                    updated_at = updated_at.replace(tzinfo=timezone.utc)
            else:
                # Якщо поля немає, використовуємо час модифікації файлу
                mtime = file_path.stat().st_mtime
                updated_at = datetime.fromtimestamp(mtime, tz=timezone.utc)
            
            if updated_at < threshold:
                logger.info(f"Deleting stale session: {file_path.name} (last updated: {updated_at})")
                file_path.unlink()
                deleted_count += 1

        except Exception as e:
            logger.error(f"Error processing session file {file_path}: {e}")
            errors_count += 1

    logger.info(f"Cleanup finished. Deleted: {deleted_count}, Errors: {errors_count}")


def clean_abandoned_sessions(active_session_ids: set[str], grace_period_minutes: int = 5):
    """
    Видаляє "покинуті" порожні сесії.
    
    Критерії видалення:
    1. Сесія не має активного SSE-з'єднання (немає в active_session_ids).
    2. Сесія "порожня" (немає записаних даних в all_data).
    3. Сесія не оновлювалася протягом grace_period_minutes (захист від короткочасних розривів).
    """
    if not _is_filesystem_backend():
        logger.debug("Non-filesystem backend detected; skipping clean_abandoned_sessions")
        return

    sessions_dir = settings.sessions_root
    if not sessions_dir.exists():
        return

    now = datetime.now(timezone.utc)
    threshold = now - timedelta(minutes=grace_period_minutes)
    
    deleted_count = 0
    
    for file_path in sessions_dir.glob("*.json"):
        try:
            # Читаємо JSON
            data = read_json(file_path)
            session_id = data.get("session_id")
            
            # Якщо сесія активна - пропускаємо
            if session_id in active_session_ids:
                continue
                
            # Перевіряємо, чи є дані
            all_data = data.get("all_data") or {}
            if all_data:
                # Є дані - не видаляємо (це робота для clean_stale_sessions)
                continue
                
            # Якщо дійшли сюди - сесія неактивна, стара і порожня. Видаляємо.
            logger.info(f"Deleting abandoned empty session: {file_path.name}")
            file_path.unlink()
            deleted_count += 1
            
        except Exception as e:
            logger.error(f"Error cleaning abandoned session {file_path}: {e}")
            
    if deleted_count > 0:
        logger.info(f"Abandoned cleanup: deleted {deleted_count} empty sessions")
