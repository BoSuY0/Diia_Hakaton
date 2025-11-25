from __future__ import annotations

import logging
import os
from typing import Optional


_CONFIGURED = False

# Опційна подія, яку можна використати для сигналізації про старт сервера
SERVER_READY_EVENT: Optional["threading.Event"] = None  # type: ignore[name-defined]


class PiiRedactionFilter(logging.Filter):
    """
    Фільтр, який намагається вирізати PII з тексту логів.

    Використовує той самий sanitize_typed(), що й основний бекенд:
    реальні значення замінюються на теги [TYPE#N]. Якщо щось іде
    не так — лог не змінюється.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
        try:
            from backend.domain.validation.pii_tagger import sanitize_typed

            msg = record.getMessage()
            sanitized = sanitize_typed(str(msg))
            record.msg = sanitized["sanitized_text"]
            record.args = ()
        except Exception:
            # У разі будь-якої помилки не блокуємо лог
            pass
        return True


class ColorFormatter(logging.Formatter):
    """
    Додає кольори до рівнів логування для виводу в термінал.
    Працює як звичайний Formatter, але підміняє record.levelname.
    """

    RESET = "\033[0m"
    COLORS = {
        "DEBUG": "\033[36m",  # cyan
        "INFO": "\033[32m",  # green
        "WARNING": "\033[33m",  # yellow
        "ERROR": "\033[31m",  # red
        "CRITICAL": "\033[35m",  # magenta
    }

    def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
        import threading

        original_levelname = record.levelname
        color = self.COLORS.get(original_levelname, "")
        if color:
            record.levelname = f"{color}{original_levelname}{self.RESET}"
        try:
            formatted = super().format(record)

            # Якщо налаштована SERVER_READY_EVENT і це стартовий лог uvicorn —
            # сигналізуємо, що сервер готовий (для launcher --test).
            global SERVER_READY_EVENT
            if (
                SERVER_READY_EVENT is not None
                and isinstance(SERVER_READY_EVENT, threading.Event)
                and record.name == "uvicorn.error"
                and "Uvicorn running on" in record.getMessage()
            ):
                SERVER_READY_EVENT.set()

            return formatted
        finally:
            record.levelname = original_levelname


def setup_logging(default_level: int = logging.INFO) -> None:
    """
    Налаштовує єдиний root-логгер для всієї системи.
    Викликається один раз; усі інші логгери (у тому числі uvicorn)
    використовують той самий формат і хендлери.
    """
    global _CONFIGURED
    root_logger = logging.getLogger()
    # Якщо хендлерів немає (наприклад, pytest очистив), переналаштовуємо навіть якщо вже конфігурований.
    if _CONFIGURED and root_logger.handlers:
        return

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, default_level)
    # Уникаємо DEBUG-рівня для прод-оточення, навіть якщо LOG_LEVEL=DEBUG
    if level < logging.INFO:
        level = logging.INFO

    root_logger.setLevel(level)

    # Прибираємо будь-які попередні хендлери (у т.ч. від uvicorn/basicConfig)
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler()
    handler.setLevel(level)
    handler.addFilter(PiiRedactionFilter())
    formatter = ColorFormatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

    # Менше шуму від HTTP-доступів, але залишаємо помилки uvicorn
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    logger = logging.getLogger(name)
    root = logging.getLogger()
    if not logger.handlers:
        for handler in root.handlers:
            logger.addHandler(handler)
    # Уникаємо дублювання виводу: локальні хендлери достатньо, propagate не потрібен
    logger.propagate = False
    return logger
