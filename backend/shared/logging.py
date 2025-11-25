"""Logging configuration and utilities."""
from __future__ import annotations

import logging
import os
import threading
from typing import Callable, Optional

# Try to import sanitize_typed at module level (may fail due to circular imports)
try:
    from backend.domain.validation.pii_tagger import sanitize_typed as _sanitize_fn
except ImportError:
    _sanitize_fn = None


class _LoggingState:
    """
    Module-level logging state container.

    Tracks logging configuration and server ready events.
    """

    configured: bool = False
    server_ready_event: Optional[threading.Event] = None

    def reset(self) -> None:
        """Reset state for testing."""
        self.configured = False
        self.server_ready_event = None

    def is_configured(self) -> bool:
        """Check if logging is configured."""
        return self.configured


_state = _LoggingState()


def _get_sanitizer() -> Optional[Callable[[str], dict]]:
    """Get sanitize_typed function."""
    return _sanitize_fn


class PiiRedactionFilter(logging.Filter):
    """
    Фільтр, який намагається вирізати PII з тексту логів.

    Використовує той самий sanitize_typed(), що й основний бекенд:
    реальні значення замінюються на теги [TYPE#N]. Якщо щось іде
    не так — лог не змінюється.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        sanitizer = _get_sanitizer()
        if sanitizer is not None:
            try:
                msg = record.getMessage()
                sanitized = sanitizer(str(msg))
                record.msg = sanitized["sanitized_text"]
                record.args = ()
            except (KeyError, TypeError, ValueError, AttributeError):
                # У разі помилки санітизації не блокуємо лог
                pass
        return True

    def __repr__(self) -> str:
        return "PiiRedactionFilter()"


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

    def format(self, record: logging.LogRecord) -> str:
        original_levelname = record.levelname
        color = self.COLORS.get(original_levelname, "")
        if color:
            record.levelname = f"{color}{original_levelname}{self.RESET}"
        try:
            formatted = super().format(record)

            # Якщо налаштована server_ready_event і це стартовий лог uvicorn —
            # сигналізуємо, що сервер готовий (для launcher --test).
            if (
                _state.server_ready_event is not None
                and isinstance(_state.server_ready_event, threading.Event)
                and record.name == "uvicorn.error"
                and "Uvicorn running on" in record.getMessage()
            ):
                _state.server_ready_event.set()

            return formatted
        finally:
            record.levelname = original_levelname


def setup_logging(default_level: int = logging.INFO) -> None:
    """
    Налаштовує єдиний root-логгер для всієї системи.
    Викликається один раз; усі інші логгери (у тому числі uvicorn)
    використовують той самий формат і хендлери.
    """
    root_logger = logging.getLogger()
    # Якщо хендлерів немає (pytest очистив), переналаштовуємо.
    if _state.configured and root_logger.handlers:
        return

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, default_level)
    # Уникаємо DEBUG-рівня для прод-оточення
    level = max(level, logging.INFO)

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

    _state.configured = True


def get_logger(name: str) -> logging.Logger:
    """Get a logger with the given name."""
    setup_logging()
    logger = logging.getLogger(name)
    root = logging.getLogger()
    if not logger.handlers:
        for handler in root.handlers:
            logger.addHandler(handler)
    # Уникаємо дублювання виводу: локальні хендлери достатньо, propagate не потрібен
    logger.propagate = False
    return logger


# Backward compatibility aliases
def set_server_ready_event(event: Optional[threading.Event]) -> None:
    """Set the server ready event for signaling."""
    _state.server_ready_event = event


def get_server_ready_event() -> Optional[threading.Event]:
    """Get the server ready event."""
    return _state.server_ready_event
