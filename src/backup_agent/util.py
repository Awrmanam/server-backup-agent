from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path
from typing import Iterable


class CommandError(RuntimeError):
    pass


def require_command(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise CommandError(f"Required command not found: {name}")
    return path


def run(
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    cwd: str | os.PathLike[str] | None = None,
    capture: bool = True,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)

    proc = subprocess.run(
        args,
        cwd=cwd,
        env=merged_env,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        check=False,
    )
    if check and proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        detail = stderr or stdout or f"exit code {proc.returncode}"
        raise CommandError(f"Command failed: {' '.join(args)}\n{detail}")
    return proc


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def split_file(path: Path, part_bytes: int) -> list[Path]:
    if part_bytes <= 0:
        raise ValueError("part_bytes must be positive")
    if path.stat().st_size <= part_bytes:
        return [path]

    parts: list[Path] = []
    with path.open("rb") as source:
        index = 1
        while True:
            chunk = source.read(part_bytes)
            if not chunk:
                break
            part = path.with_name(f"{path.name}.part-{index:03d}")
            with part.open("wb") as target:
                target.write(chunk)
            parts.append(part)
            index += 1
    return parts


def cleanup_parts(parts: Iterable[Path], original: Path) -> None:
    for part in parts:
        if part != original:
            part.unlink(missing_ok=True)


def remove_old_files(directory: Path, retention_days: int) -> int:
    if retention_days < 0:
        return 0
    cutoff = __import__("time").time() - retention_days * 86400
    removed = 0
    for item in directory.iterdir():
        try:
            if item.is_file() and item.stat().st_mtime < cutoff:
                item.unlink()
                removed += 1
        except FileNotFoundError:
            pass
    return removed
