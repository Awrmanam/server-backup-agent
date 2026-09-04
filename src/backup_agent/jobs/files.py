from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backup_agent.jobs.common import BackupArtifact
from backup_agent.util import run, sha256_file


def create_files_backup(job: dict[str, Any], agent: dict[str, Any]) -> BackupArtifact:
    job_name = str(job["name"])
    raw_paths = [str(item) for item in job.get("paths", [])]
    if not raw_paths:
        raise RuntimeError(f"Files job {job_name!r} has no paths")

    paths = [Path(p) for p in raw_paths]
    missing = [str(p) for p in paths if not (p.exists() or p.is_symlink())]
    if missing:
        raise RuntimeError("Backup paths not found: " + ", ".join(missing))

    output_root = Path(str(agent["work_dir"])).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    os.chmod(output_root, 0o700)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
    temp_dir = Path(tempfile.mkdtemp(prefix=f".{job_name}-{stamp}-", dir=output_root))
    final_path = output_root / f"{job_name}-{stamp}.tar.gz"

    try:
        data_archive = temp_dir / "files.tar.gz"
        relative_paths = [str(p).lstrip("/") for p in paths]
        run(["tar", "-czpf", str(data_archive), "-C", "/", *relative_paths])
        run(["tar", "-tzf", str(data_archive)])

        manifest = {
            "format": 1,
            "job": job_name,
            "type": "files",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "server_name": str(agent.get("server_name", "")),
            "paths": raw_paths,
            "inner_sha256": {"files.tar.gz": sha256_file(data_archive)},
        }
        (temp_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        run(["tar", "-czf", str(final_path), "-C", str(temp_dir), "."])
        run(["tar", "-tzf", str(final_path)])
        os.chmod(final_path, 0o600)

        return BackupArtifact(
            job_name=job_name,
            path=final_path,
            metadata={"created_utc": manifest["created_utc"], "paths": raw_paths},
        )
    finally:
        import shutil

        shutil.rmtree(temp_dir, ignore_errors=True)
