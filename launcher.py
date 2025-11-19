from __future__ import annotations

import argparse
import os
import sys
import threading
from typing import Optional
from uuid import uuid4

import uvicorn

import src.common.logging as common_logging
from src.common.logging import get_logger, setup_logging


logger = get_logger(__name__)


def run_app(
    host: str = "0.0.0.0",
    port: int = 8000,
    reload: bool = True,
) -> None:
    """
    Головна точка входу для запуску всієї аппки.

    1. Налаштовує єдиний логгер.
    2. Запускає FastAPI-сервер (src.app.server:app) через uvicorn.
    """
    # Єдине налаштування логування для всієї системи
    setup_logging()

    logger.info("Starting API server on %s:%d", host, port)
    uvicorn.run(
        "src.app.server:app",
        host=host,
        port=port,
        reload=reload,
        # Використовуємо наше глобальне налаштування logging,
        # uvicorn не перестворює власні хендлери/форматери
        log_config=None,
    )


def run_cli_chat(session_id: Optional[str] = None) -> None:
    """
    Простий CLI-режим для девелопмента.

    Використовує ті самі handler-и, що й HTTP /chat, але без підняття uvicorn.
    """
    from src.app.server import ChatRequest, chat, on_startup  # type: ignore[import]

    setup_logging()
    on_startup()

    if not session_id:
        session_id = f"cli-dev-session-{uuid4().hex[:8]}"

    print("=== CLI dev chat ===")
    print("Session ID:", session_id)
    print("Введіть повідомлення (Ctrl+C для виходу).")

    try:
        while True:
            try:
                text = input("you> ").strip()
            except EOFError:
                print()
                break
            if not text:
                continue
            req = ChatRequest(session_id=session_id, message=text)
            try:
                resp = chat(req)
            except Exception as exc:  # pragma: no cover - dev helper
                logger.exception("CLI chat error: %s", exc)
                print(f"bot> [error] {exc}")
                continue
            print(f"bot> {resp.reply}")
    except KeyboardInterrupt:
        print("\nДо зустрічі!")


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description="Запуск FastAPI-сервера або CLI-чату для девелопмента.",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Запустити HTTP-сервер і CLI чат-меню для девелопмента.",
    )
    parser.add_argument(
        "--host",
        default=os.getenv("APP_HOST", "0.0.0.0"),
        help="Хост для HTTP-сервера (за замовчуванням APP_HOST або 0.0.0.0).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("APP_PORT", "8000")),
        help="Порт для HTTP-сервера (за замовчуванням APP_PORT або 8000).",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        default=os.getenv("APP_RELOAD", "true").lower() == "true",
        help="Увімкнути авто-перезапуск uvicorn (тільки для девелопмента).",
    )
    parser.add_argument(
        "--session-id",
        dest="session_id",
        default=None,
        help="Ідентифікатор сесії для CLI-режиму (якщо не вказано — буде згенеровано випадковий).",
    )

    args = parser.parse_args(argv or sys.argv[1:])

    if args.test:
        # У dev-режимі одночасно запускаємо HTTP-сервер (у бекграунді)
        # та CLI-чат у поточному процесі.
        server_ready = threading.Event()
        # Повідомляємо модулю логування, куди сигналізувати про старт uvicorn
        common_logging.SERVER_READY_EVENT = server_ready  # type: ignore[attr-defined]

        server_thread = threading.Thread(
            target=run_app,
            kwargs={
                "host": args.host,
                "port": args.port,
                "reload": False,
            },
            daemon=True,
        )
        server_thread.start()
        # Чекаємо, поки uvicorn виведе свій стартовий лог
        server_ready.wait()
        run_cli_chat(session_id=args.session_id)
    else:
        run_app(host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
