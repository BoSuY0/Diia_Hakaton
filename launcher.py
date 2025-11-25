"""Application launcher for API server and CLI chat."""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import threading
from typing import Optional
from uuid import uuid4

import uvicorn

import backend.shared.logging as common_logging
from backend.shared.logging import get_logger, setup_logging


logger = get_logger(__name__)


def kill_process_on_port(port: int) -> None:
    """
    Знаходить і завершує процес, який слухає на вказаному порту.
    Корисно для автоматичного перезапуску сервера в режимі розробки.
    """
    import signal  # pylint: disable=import-outside-toplevel
    import subprocess  # pylint: disable=import-outside-toplevel

    try:
        if sys.platform == "win32":
            # Windows implementation
            cmd = f"netstat -ano | findstr :{port}"
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, check=False,
            )
            if result.stdout:
                # Parse output to find PID. Format: PROTO Local Address Foreign Address State PID
                # TCP    0.0.0.0:8000           0.0.0.0:0              LISTENING       1234
                lines = result.stdout.strip().split('\n')
                for line in lines:
                    parts = line.split()
                    if len(parts) >= 5 and f":{port}" in parts[1]:
                        pid = int(parts[-1])
                        logger.info(
                            "Found process %d on port %d, terminating...", pid, port,
                        )
                        subprocess.run(
                            f"taskkill /F /PID {pid}",
                            shell=True, capture_output=True, check=False,
                        )
                        logger.info("Process %d terminated", pid)
                        import time  # pylint: disable=import-outside-toplevel
                        time.sleep(1)
                        return
        else:
            # Unix implementation
            # Знайти PID процесу на порту
            result = subprocess.run(
                ["lsof", "-t", f"-i:{port}"],
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode == 0 and result.stdout.strip():
                pid = int(result.stdout.strip().split()[0])
                logger.info(
                    "Found process %d on port %d, terminating...", pid, port,
                )

                try:
                    os.kill(pid, signal.SIGTERM)
                    logger.info("Process %d terminated successfully", pid)
                    # Дати ОС час звільнити порт
                    import time  # pylint: disable=import-outside-toplevel
                    time.sleep(1)
                except ProcessLookupError:
                    logger.warning("Process %d already dead", pid)
                except PermissionError:
                    logger.error("No permission to kill process %d", pid)
                return

    except (OSError, ValueError, subprocess.SubprocessError):
        # Fallback - continue to try fuser
        pass

    if sys.platform != "win32":
        # lsof не встановлено, пробуємо fuser (тільки Linux/Mac)
        try:
            result = subprocess.run(
                ["fuser", "-k", f"{port}/tcp"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                logger.info("Killed process on port %d using fuser", port)
        except FileNotFoundError:
            logger.warning("Neither lsof nor fuser available, cannot auto-kill old server")
        except (OSError, subprocess.SubprocessError) as e:
            logger.warning("Could not kill process on port %d: %s", port, e)


def run_app(
    host: str = "0.0.0.0",
    port: int = 8000,
    reload: bool = False,
) -> None:
    """
    Головна точка входу для запуску всієї аппки.

    1. Налаштовує єдиний логгер.
    2. Запускає FastAPI-сервер (backend.api.http.server:app) через uvicorn.
    """
    # Єдине налаштування логування для всієї системи
    setup_logging()

    # Автоматично завершити старий процес на цьому порту (якщо є)
    kill_process_on_port(port)

    logger.info("Starting API server on %s:%d", host, port)
    uvicorn_kwargs = {
        "app": "backend.api.http.server:app",
        "host": host,
        "port": port,
        # Використовуємо наше глобальне налаштування logging,
        # uvicorn не перестворює власні хендлери/форматери
        "log_config": None,
        "timeout_keep_alive": 5,
        "timeout_graceful_shutdown": 3,
    }

    if reload:
        uvicorn_kwargs.update(
            {
                "reload": True,
                "reload_dirs": [os.path.join(os.getcwd(), "src")],
                "reload_excludes": [
                    "venv",
                    ".venv",
                    "client",
                    "node_modules",
                    ".git",
                    "__pycache__",
                    "site-packages",
                ],
            }
        )

    uvicorn.run(**uvicorn_kwargs)


def run_cli_chat(session_id: Optional[str] = None) -> None:
    """
    Простий CLI-режим для девелопмента.

    Використовує ті самі handler-и, що й HTTP /chat, але без підняття uvicorn.
    """
    from backend.api.http.server import ChatRequest, chat  # pylint: disable=import-outside-toplevel
    from backend.infra.storage.fs import ensure_directories  # pylint: disable=import-outside-toplevel

    setup_logging()
    ensure_directories()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

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
                resp = loop.run_until_complete(chat(req))
            except (RuntimeError, ValueError, OSError) as exc:  # pragma: no cover
                logger.exception("CLI chat error: %s", exc)
                print(f"bot> [error] {exc}")
                continue
            print(f"bot> {resp.reply}")
    except KeyboardInterrupt:
        print("\nДо зустрічі!")
    finally:
        try:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        except (RuntimeError, asyncio.CancelledError):
            pass
        loop.call_soon(loop.stop)
        loop.close()


def main(argv: Optional[list[str]] = None) -> None:
    """Main entry point for the launcher CLI."""
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
        default=int(os.getenv("APP_PORT", os.getenv("PORT", "8000"))),
        help="Порт для HTTP-сервера (APP_PORT, PORT або 8000).",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        default=os.getenv("APP_RELOAD", "false").lower() == "true",
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
