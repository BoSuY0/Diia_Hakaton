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


def kill_process_on_port(port: int) -> None:
    """
    Знаходить і завершує процес, який слухає на вказаному порту.
    Корисно для автоматичного перезапуску сервера в режимі розробки.
    """
    import signal
    import subprocess
    
    try:
        if sys.platform == "win32":
            # Windows implementation
            cmd = f"netstat -ano | findstr :{port}"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if result.stdout:
                # Parse output to find PID. Format: PROTO Local Address Foreign Address State PID
                # TCP    0.0.0.0:8000           0.0.0.0:0              LISTENING       1234
                lines = result.stdout.strip().split('\n')
                for line in lines:
                    parts = line.split()
                    if len(parts) >= 5 and f":{port}" in parts[1]:
                        pid = int(parts[-1])
                        logger.info(f"Found process {pid} on port {port}, terminating...")
                        subprocess.run(f"taskkill /F /PID {pid}", shell=True, capture_output=True)
                        logger.info(f"Process {pid} terminated")
                        import time
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
                logger.info(f"Found process {pid} on port {port}, terminating...")
                
                try:
                    os.kill(pid, signal.SIGTERM)
                    logger.info(f"Process {pid} terminated successfully")
                    # Дати ОС час звільнити порт
                    import time
                    time.sleep(1)
                except ProcessLookupError:
                    logger.warning(f"Process {pid} already dead")
                except PermissionError:
                    logger.error(f"No permission to kill process {pid}")
                return
                
    except Exception as e:
        # Fallback or error logging
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
                logger.info(f"Killed process on port {port} using fuser")
        except FileNotFoundError:
            logger.warning("Neither lsof nor fuser available, cannot auto-kill old server")
        except Exception as e:
            logger.warning(f"Could not kill process on port {port}: {e}")


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

    # Автоматично завершити старий процес на цьому порту (якщо є)
    kill_process_on_port(port)

    logger.info("Starting API server on %s:%d", host, port)
    uvicorn.run(
        "src.app.server:app",
        host=host,
        port=port,
        reload=reload,
        reload_dirs=[os.path.join(os.getcwd(), "src")],
        reload_excludes=["venv", ".venv", "client", "node_modules", ".git", "__pycache__", "site-packages"],
        # Використовуємо наше глобальне налаштування logging,
        # uvicorn не перестворює власні хендлери/форматери
        log_config=None,
        timeout_keep_alive=5,
        timeout_graceful_shutdown=3,
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
