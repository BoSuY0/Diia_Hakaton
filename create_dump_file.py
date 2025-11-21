from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import fnmatch

BASE_DIR = Path(__file__).resolve().parent
DUMPS_DIR = BASE_DIR / "dumps"


def ensure_dumps_dir() -> Path:
    DUMPS_DIR.mkdir(parents=True, exist_ok=True)
    return DUMPS_DIR


def create_dump_file(
    content: str,
    *,
    file_name: Optional[str] = None,
) -> Path:
    """
    Створює дамп-файл у директорії /dumps/ з розширенням .txt.

    Вміст файлу (content) визначає розробник, який викликає цей скрипт
    (через імпорт функції або CLI).
    """
    dumps_dir = ensure_dumps_dir()

    suffix = ".txt"

    if file_name:
        file_path = dumps_dir / f"{file_name}{suffix}"
    else:
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        file_path = dumps_dir / f"dump_{timestamp}{suffix}"

    file_path.write_text(content, encoding="utf-8")
    return file_path


def _load_gitignore_patterns(base_dir: Path) -> tuple[list[str], object | None]:
    """
    Читає .gitignore в корені проєкту і повертає
    - список сирих патернів
    - скомпільований PathSpec (якщо модуль pathspec доступний).
    """
    gitignore_path = base_dir / ".gitignore"
    if not gitignore_path.exists():
        return [], None
    lines = gitignore_path.read_text(encoding="utf-8").splitlines()
    patterns: list[str] = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(line)
    try:
        from pathspec import PathSpec  # type: ignore
    except ModuleNotFoundError:
        return patterns, None
    return patterns, PathSpec.from_lines("gitwildmatch", patterns)


def collect_project_files() -> list[Path]:
    """
    Повертає список файлів проєкту, відфільтрованих згідно з .gitignore.
    Використовує pathspec для точного застосування .gitignore (якщо доступний),
    і простий fallback у разі відсутності залежності.
    """
    patterns, gitignore_spec = _load_gitignore_patterns(BASE_DIR)

    def is_ignored(rel: Path, *, is_dir: bool = False) -> bool:
        rel_str = rel.as_posix()
        candidates = [rel_str]
        if is_dir and not rel_str.endswith("/"):
            candidates.append(rel_str + "/")

        if gitignore_spec:
            for candidate in candidates:
                if gitignore_spec.match_file(candidate):
                    return True

        for pat in patterns:
            # Директорія: 'dir/' → будь-що всередині
            if pat.endswith("/"):
                prefix = pat[:-1]
                if rel_str == prefix or rel_str.startswith(prefix + "/"):
                    return True
            # Звичайний glob-патерн
            elif fnmatch.fnmatch(rel_str, pat):
                return True
        return False

    all_paths: list[Path] = []
    for root, dirs, files in os.walk(BASE_DIR):
        root_path = Path(root)
        rel_root = root_path.relative_to(BASE_DIR)

        # Не заходимо в директорії, які ігноруються .gitignore
        dirs[:] = [d for d in dirs if not is_ignored(rel_root / d, is_dir=True)]

        for file_name in files:
            rel = rel_root / file_name
            # Не включаємо файли у dumps, навіть якщо не прописані в .gitignore
            if str(rel).startswith("dumps/"):
                continue
            if is_ignored(rel):
                continue
            file_path = BASE_DIR / rel
            try:
                if not file_path.is_file():
                    continue
            except OSError:
                # Пропускаємо файли/лінки, які неможливо прочитати (наприклад, lib64 у venv на Windows)
                continue
            all_paths.append(rel)
    return sorted(all_paths)


def create_full_project_dump(file_name: Optional[str] = None) -> Path:
    """
    Створює текстовий дамп у форматі:

    ===== FILE: relative/path =====
    <вміст файлу>

    для всіх файлів проєкту, які не ігноруються .gitignore.
    """
    files = collect_project_files()
    parts: list[str] = []
    for rel in files:
        parts.append(f"===== FILE: {rel} =====")
        try:
            parts.append(
                (BASE_DIR / rel).read_text(encoding="utf-8", errors="replace")
            )
        except OSError as exc:
            parts.append(f"<<unable to read file: {exc}>>")
        parts.append("")  # порожній рядок між файлами

    content = "\n".join(parts)
    if not file_name:
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        file_name = f"full_project_dump_{timestamp}"
    return create_dump_file(content=content, file_name=file_name)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Створення дамп-файлу у директорії ./dumps/"
    )
    parser.add_argument(
        "-n",
        "--name",
        dest="file_name",
        help="Ім'я дамп-файлу (без .txt, опційно)",
    )
    parser.add_argument(
        "-c",
        "--content",
        dest="content",
        help="Контент дампа. Якщо не вказано — читається з stdin",
    )
    parser.add_argument(
        "--full-project",
        action="store_true",
        help="Зібрати повний дамп проєкту (усі файли, що не ігноруються .gitignore)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv or sys.argv[1:])

    if args.full_project:
        file_path = create_full_project_dump(file_name=args.file_name)
        print(str(file_path))
        return

    if args.content is not None:
        content = args.content
    else:
        # Читаємо з stdin (можна передати будь-який текст/JSON/log)
        content = sys.stdin.read()

    if not content:
        print("Немає контенту для дампа (content порожній).", file=sys.stderr)
        sys.exit(1)

    file_path = create_dump_file(
        content=content,
        file_name=args.file_name,
    )
    print(str(file_path))


if __name__ == "__main__":
    main()
