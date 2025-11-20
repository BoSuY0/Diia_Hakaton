from __future__ import annotations

import json
import os
import time
import random
import threading
from pathlib import Path
from typing import Any, Optional
from contextlib import contextmanager

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

    def acquire(self) -> None:
        thread_id = threading.get_ident()

        # Check in-memory reentrancy first
        with self._memory_lock_mutex:
            if self.lock_path in self._memory_locks:
                owner, count = self._memory_locks[self.lock_path]
                if owner == thread_id:
                    self._memory_locks[self.lock_path] = (owner, count + 1)
                    self._acquired = True
                    return

        # Try to acquire physical file lock
        start_time = time.time()
        while True:
            try:
                # Attempt atomic create
                with open(self.lock_path, "x"):
                    self._acquired = True
                    # Mark as owned by this thread
                    with self._memory_lock_mutex:
                        self._memory_locks[self.lock_path] = (thread_id, 1)
                    return
            except FileExistsError:
                # Check timeout
                if time.time() - start_time > self.timeout:
                    raise TimeoutError(f"Could not acquire lock for {self.path} after {self.timeout}s")
                
                # Check for stale lock (e.g. process crash)
                try:
                    stat = self.lock_path.stat()
                    # Hardcoded strict stale time (e.g. 30s)
                    # If a transaction takes >30s, it's likely dead.
                    if time.time() - stat.st_mtime > 30.0:
                        try:
                            os.remove(self.lock_path)
                        except OSError:
                            pass # Race to delete
                except OSError:
                    pass # Lock file might have been removed by other process

                time.sleep(random.uniform(0.05, 0.1))

    def release(self) -> None:
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
                    else:
                        # Last release, remove physical lock
                        del self._memory_locks[self.lock_path]

        try:
            os.remove(self.lock_path)
        except OSError:
            pass # Already gone?
        self._acquired = False

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()


def read_json(path: Path) -> Any:
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
