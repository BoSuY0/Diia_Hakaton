"""File system utilities for session storage and file locking."""
from __future__ import annotations

import json
import os
import random
import threading
import time
from pathlib import Path
from typing import Any

import aiofiles

from backend.infra.config.settings import settings
from backend.shared.async_utils import run_sync


def ensure_directories() -> None:
    """Create all required directories for the application."""
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
    """Get the path to session answers JSON file."""
    return settings.sessions_root / f"session_{session_id}.json"


def output_document_path(template_id: str, session_id: str, ext: str = "docx") -> Path:
    """Get the path for output document."""
    filename = f"{template_id}_{session_id}.{ext}"
    return settings.output_root / filename


class FileLock:
    """
    Inter-process file lock based on .lock file existence.
    Includes reentrancy support for the same thread.
    """

    # Class-level dictionary to track locks held by current process/threads
    # Key: lock_path, Value: (owner_thread_ident, recursion_count)
    _memory_locks = {}
    _memory_lock_mutex = threading.RLock()

    def __init__(self, path: Path, timeout: float = 10.0):
        self.path = path
        self.lock_path = path.with_suffix(path.suffix + ".lock")
        self.timeout = timeout
        self._acquired = False

    def _try_reentrant_acquire(self, thread_id: int) -> bool:
        """Try to acquire lock if already held by this thread."""
        with self._memory_lock_mutex:
            if self.lock_path in self._memory_locks:
                owner, count = self._memory_locks[self.lock_path]
                if owner == thread_id:
                    self._memory_locks[self.lock_path] = (owner, count + 1)
                    self._acquired = True
                    return True
        return False

    def _is_held_by_sibling(self) -> bool:
        """Check if lock is held by another thread in this process."""
        with self._memory_lock_mutex:
            return self.lock_path in self._memory_locks

    def _create_lock_file(self, thread_id: int) -> bool:
        """Try to create the lock file atomically."""
        try:
            with open(self.lock_path, "x", encoding="utf-8") as f:
                f.write(str(os.getpid()))
                f.flush()
                os.fsync(f.fileno())
            self._acquired = True
            with self._memory_lock_mutex:
                self._memory_locks[self.lock_path] = (thread_id, 1)
            return True
        except FileExistsError:
            return False

    def _check_and_remove_stale_lock(self) -> None:
        """Check if lock file is stale and remove it if so."""
        try:
            lock_pid = self._read_lock_pid()
            if self._is_lock_stale(lock_pid):
                try:
                    os.remove(self.lock_path)
                except OSError:
                    pass
        except OSError:
            pass

    def _read_lock_pid(self) -> int | None:
        """Read PID from lock file."""
        try:
            with open(self.lock_path, "r", encoding="utf-8") as f:
                pid_str = f.read().strip()
            return int(pid_str) if pid_str else None
        except (ValueError, OSError):
            return None

    def _is_lock_stale(self, lock_pid: int | None) -> bool:
        """Determine if lock is stale based on PID or file age."""
        if lock_pid and lock_pid == os.getpid():
            return True
        if lock_pid:
            try:
                os.kill(lock_pid, 0)
                return False
            except OSError:
                return True
        stat = self.lock_path.stat()
        return time.time() - stat.st_mtime > 30.0

    def acquire(self) -> None:
        """Acquire the file lock with timeout."""
        thread_id = threading.get_ident()

        if self._try_reentrant_acquire(thread_id):
            return

        start_time = time.time()
        while True:
            if self._is_held_by_sibling():
                if time.time() - start_time > self.timeout:
                    raise TimeoutError(
                        f"Could not acquire lock for {self.path} after {self.timeout}s"
                    )
                time.sleep(0.05)
                continue

            if self._create_lock_file(thread_id):
                return

            if time.time() - start_time > self.timeout:
                raise TimeoutError(
                    f"Could not acquire lock for {self.path} after {self.timeout}s"
                )

            self._check_and_remove_stale_lock()
            time.sleep(random.uniform(0.05, 0.1))

    def release(self) -> None:
        """Release the file lock."""
        if not self._acquired:
            return

        thread_id = threading.get_ident()
        with self._memory_lock_mutex:
            if self.lock_path in self._memory_locks:
                owner, count = self._memory_locks[self.lock_path]
                if owner == thread_id:
                    if count > 1:
                        self._memory_locks[self.lock_path] = (owner, count - 1)
                        self._acquired = False
                        return
                    # Last release, remove physical lock
                    del self._memory_locks[self.lock_path]

        # Retry deletion a few times to handle Windows transient file locking (e.g. antivirus)
        for _ in range(3):
            try:
                os.remove(self.lock_path)
                break
            except OSError:
                time.sleep(0.01)

        self._acquired = False

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()


def read_json(path: Path) -> Any:
    """Read and parse JSON file."""
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any, locked_by_caller: bool = False) -> None:
    """
    Writes JSON to file.
    If locked_by_caller is True, skips acquiring lock (assumes caller holds it).
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    if locked_by_caller:
        _write_atomic(path, data)
    else:
        with FileLock(path):
            _write_atomic(path, data)

def _write_atomic(path: Path, data: Any) -> None:
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


# Async wrappers to avoid blocking event loop
async def read_json_async(path: Path) -> Any:
    """Read and parse JSON file asynchronously."""
    async with aiofiles.open(path, "r", encoding="utf-8") as f:
        content = await f.read()
    return json.loads(content)


async def write_json_async(path: Path, data: Any, locked_by_caller: bool = False) -> None:
    """Write JSON to file asynchronously."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if locked_by_caller:
        await _write_atomic_async(path, data)
    else:
        # FileLock is sync; use threadpool to avoid blocking loop
        await run_sync(write_json, path, data, locked_by_caller=locked_by_caller)


async def _write_atomic_async(path: Path, data: Any) -> None:
    tmp_path = path.with_suffix(".tmp")
    try:
        async with aiofiles.open(tmp_path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(data, ensure_ascii=False, indent=2))
            await f.flush()
        await run_sync(os.replace, tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
