import json
import os
import threading
import time
from pathlib import Path

import pytest

from backend.infra.storage.fs import FileLock, write_json, session_answers_path, output_document_path


def test_filelock_reentrant_same_thread(tmp_path):
    target = tmp_path / "file.json"
    lock = FileLock(target)
    with lock:
        with lock:  # reentrant should not deadlock
            write_json(target, {"a": 1}, locked_by_caller=True)
    assert json.loads(target.read_text(encoding="utf-8"))["a"] == 1


def test_filelock_blocks_other_thread(tmp_path):
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
    nested = tmp_path / "a" / "b" / "c.json"
    write_json(nested, {"k": "v"})
    assert nested.exists()
    assert json.loads(nested.read_text(encoding="utf-8"))["k"] == "v"


def test_session_and_output_paths_use_ids(mock_settings):
    sid = "abc"
    template_id = "templ"
    sess_path = session_answers_path(sid)
    out_path = output_document_path(template_id, sid)
    assert str(sess_path).endswith(f"session_{sid}.json")
    assert out_path.name == f"{template_id}_{sid}.docx"
