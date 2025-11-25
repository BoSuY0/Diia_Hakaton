"""Tests for file locking functionality."""
import json
import threading

import pytest

from backend.infra.storage.fs import (
    FileLock,
    output_document_path,
    session_answers_path,
    write_json,
)


def test_filelock_reentrant_same_thread(tmp_path):
    """Test reentrant file locking in same thread."""
    target = tmp_path / "file.json"
    lock = FileLock(target)
    with lock:
        with lock:  # reentrant should not deadlock
            write_json(target, {"a": 1}, locked_by_caller=True)
    assert json.loads(target.read_text(encoding="utf-8"))["a"] == 1


def test_filelock_blocks_other_thread(tmp_path):
    """Test file lock blocks other threads."""
    target = tmp_path / "file.json"
    lock = FileLock(target, timeout=1.0)

    acquired = []

    def worker():
        try:
            with FileLock(target, timeout=0.3):
                acquired.append("other")
        except TimeoutError:
            acquired.append("timeout")

    with lock:
        t = threading.Thread(target=worker)
        t.start()
        t.join()
    assert acquired == ["timeout"]


def test_write_json_creates_directories(tmp_path):
    """Test write_json creates parent directories."""
    nested = tmp_path / "a" / "b" / "c.json"
    write_json(nested, {"k": "v"})
    assert nested.exists()
    assert json.loads(nested.read_text(encoding="utf-8"))["k"] == "v"


@pytest.mark.usefixtures("mock_settings")
def test_session_and_output_paths_use_ids():
    """Test session and output paths use IDs correctly."""
    sid = "abc"
    template_id = "templ"
    sess_path = session_answers_path(sid)
    out_path = output_document_path(template_id, sid)
    assert str(sess_path).endswith(f"session_{sid}.json")
    assert out_path.name == f"{template_id}_{sid}.docx"
