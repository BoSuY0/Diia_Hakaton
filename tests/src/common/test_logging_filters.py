import logging

from backend.shared.logging import PiiRedactionFilter, ColorFormatter, setup_logging, get_logger


def test_pii_redaction_filter_replaces_message():
    filt = PiiRedactionFilter()
    record = logging.LogRecord("test", logging.INFO, "", 0, "IBAN UA21 3223 1300 0002 6007 2335 6600 1", args=(), exc_info=None)
    assert filt.filter(record) is True
    assert "IBAN" in record.msg and "[" in record.msg  # tag inserted


def test_color_formatter_preserves_level():
    fmt = ColorFormatter("%(levelname)s %(message)s")
    record = logging.LogRecord("test", logging.WARNING, "", 0, "msg", args=(), exc_info=None)
    formatted = fmt.format(record)
    assert "WARNING" in formatted
    assert record.levelname == "WARNING"


def test_setup_logging_idempotent():
    setup_logging()
    setup_logging()  # second call should not override handlers
    logger = get_logger("test_logger")
    assert logger.handlers
