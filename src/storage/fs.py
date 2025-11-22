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
from src.common.async_utils import run_sync
import aiofiles


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
            # Optimization: Check if held by another thread in THIS process first
            # This avoids "File in use" errors on Windows when one thread tries to delete 
            # while others are reading the PID.
            with self._memory_lock_mutex:
                if self.lock_path in self._memory_locks:
                    # Held by sibling thread. Sleep and retry without touching file.
                    if time.time() - start_time > self.timeout:
                        raise TimeoutError(f"Could not acquire lock for {self.path} after {self.timeout}s")
                    time.sleep(0.05)
                    continue

            try:
                # Attempt atomic create
                # Write PID to lock file for better stale detection
                with open(self.lock_path, "x", encoding="utf-8") as f:
                    f.write(str(os.getpid()))
                    f.flush()
                    os.fsync(f.fileno())
                
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
                    # Read PID from lock file
                    try:
                        with open(self.lock_path, "r", encoding="utf-8") as f:
                            pid_str = f.read().strip()
                        lock_pid = int(pid_str) if pid_str else None
                    except (ValueError, OSError):
                        lock_pid = None

                    is_stale = False
                    if lock_pid:
                        if lock_pid == os.getpid():
                            # Lock file says it's us, but we don't have it in memory (checked above).
                            # This means we failed to delete it previously. It's stale.
                            is_stale = True
                        else:
                            # Check if other process exists
                            try:
                                os.kill(lock_pid, 0)
                            except OSError:
                                # Process does not exist -> Stale lock
                                is_stale = True
                    else:
                        # No PID or empty file -> Fallback to time check
                        stat = self.lock_path.stat()
                        if time.time() - stat.st_mtime > 30.0:
                            is_stale = True

                    if is_stale:
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
    async with aiofiles.open(path, "r", encoding="utf-8") as f:
        content = await f.read()
    return json.loads(content)


async def write_json_async(path: Path, data: Any, locked_by_caller: bool = False) -> None:
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
