from __future__ import annotations

import gzip
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backup_agent.jobs.common import BackupArtifact
from backup_agent.util import CommandError, require_command, run, sha256_file


def _read_db_config(php_config: Path) -> dict[str, str]:
    require_command("php")
    code = r'''
$config = $argv[1];
ob_start();
include $config;
ob_end_clean();
$payload = [
  "host" => $dbhost ?? "",
  "name" => $dbname ?? "",
  "user" => $usernamedb ?? "",
  "password" => $passworddb ?? "",
];
echo json_encode($payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
'''
    proc = run(["php", "-r", code, str(php_config)])
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Could not parse database settings from {php_config}") from exc

    for key in ("host", "name", "user"):
        if not str(data.get(key, "")).strip():
            raise RuntimeError(f"Database field {key!r} is empty in {php_config}")
    return {key: str(data.get(key, "")) for key in ("host", "name", "user", "password")}


def _dump_database(db: dict[str, str], output: Path) -> None:
    mysqldump = require_command("mysqldump")
    gzip_bin = require_command("gzip")
    env = os.environ.copy()
    env["MYSQL_PWD"] = db["password"]

    dump_cmd = [
        mysqldump,
        "-h", db["host"],
        "-u", db["user"],
        "--single-transaction",
        "--quick",
        "--routines",
        "--triggers",
        "--events",
        "--hex-blob",
        "--default-character-set=utf8mb4",
        "--no-tablespaces",
        db["name"],
    ]

    with output.open("wb") as target:
        dump = subprocess.Popen(
            dump_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        assert dump.stdout is not None
        compressor = subprocess.Popen(
            [gzip_bin, "-9"],
            stdin=dump.stdout,
            stdout=target,
            stderr=subprocess.PIPE,
        )
        dump.stdout.close()
        _, dump_err = dump.communicate()
        _, gzip_err = compressor.communicate()

    if dump.returncode != 0:
        output.unlink(missing_ok=True)
        raise CommandError(
            "mysqldump failed: " + dump_err.decode("utf-8", errors="replace").strip()
        )
    if compressor.returncode != 0:
        output.unlink(missing_ok=True)
        raise CommandError(
            "gzip failed: " + gzip_err.decode("utf-8", errors="replace").strip()
        )

    run([gzip_bin, "-t", str(output)])


def _archive_bot(bot_dir: Path, output: Path) -> None:
    require_command("tar")
    run(
        [
            "tar",
            "-czpf",
            str(output),
            "-C",
            str(bot_dir.parent),
            bot_dir.name,
        ]
    )
    run(["tar", "-tzf", str(output)])


def _write_optional_command(output: Path, command: list[str]) -> None:
    try:
        proc = run(command)
        output.write_text(proc.stdout or "", encoding="utf-8")
    except Exception as exc:  # metadata should not invalidate a usable DB/files backup
        output.write_text(f"Unavailable: {exc}\n", encoding="utf-8")


def _archive_server_config(work: Path, paths: list[str]) -> Path | None:
    existing: list[str] = []
    for raw in paths:
        path = Path(raw)
        if path.exists() or path.is_symlink():
            existing.append(str(path).lstrip("/"))

    if not existing:
        return None

    output = work / "server-config.tar.gz"
    run(["tar", "-czpf", str(output), "-C", "/", *existing])
    run(["tar", "-tzf", str(output)])
    return output


def create_mirza_backup(job: dict[str, Any], agent: dict[str, Any]) -> BackupArtifact:
    job_name = str(job["name"])
    bot_dir = Path(str(job.get("bot_dir", ""))).resolve()
    php_config = Path(str(job.get("php_config", bot_dir / "config.php"))).resolve()

    if not bot_dir.is_dir():
        raise RuntimeError(f"Mirza bot directory not found: {bot_dir}")
    if not php_config.is_file():
        raise RuntimeError(f"Mirza config.php not found: {php_config}")

    output_root = Path(str(agent["work_dir"])).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    os.chmod(output_root, 0o700)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
    temp_dir = Path(tempfile.mkdtemp(prefix=f".{job_name}-{stamp}-", dir=output_root))
    final_path = output_root / f"{job_name}-{stamp}.tar.gz"

    try:
        db = _read_db_config(php_config)

        database_dump = temp_dir / "database.sql.gz"
        _dump_database(db, database_dump)

        bot_archive = temp_dir / "bot-files.tar.gz"
        _archive_bot(bot_dir, bot_archive)

        metadata_dir = temp_dir / "metadata"
        metadata_dir.mkdir(mode=0o700)

        db_info = {
            "host": db["host"],
            "database": db["name"],
            "user": db["user"],
            "password_included_in_bot_config_backup": True,
        }
        (metadata_dir / "database-info.json").write_text(
            json.dumps(db_info, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        _write_optional_command(metadata_dir / "root-crontab.txt", ["crontab", "-l"])
        _write_optional_command(
            metadata_dir / "packages.txt",
            ["dpkg-query", "-W", "-f=${binary:Package}\t${Version}\n"],
        )
        _write_optional_command(metadata_dir / "php-modules.txt", ["php", "-m"])
        _write_optional_command(metadata_dir / "hostnamectl.txt", ["hostnamectl"])

        server_archive: Path | None = None
        if bool(job.get("include_server_config", True)):
            configured_paths = [str(p) for p in job.get("server_paths", [])]
            server_archive = _archive_server_config(temp_dir, configured_paths)

        inner_hashes = {
            "database.sql.gz": sha256_file(database_dump),
            "bot-files.tar.gz": sha256_file(bot_archive),
        }
        if server_archive:
            inner_hashes[server_archive.name] = sha256_file(server_archive)

        manifest = {
            "format": 1,
            "job": job_name,
            "type": "mirza",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "server_name": str(agent.get("server_name", "")),
            "bot_dir": str(bot_dir),
            "php_config": str(php_config),
            "database": {"host": db["host"], "name": db["name"], "user": db["user"]},
            "inner_sha256": inner_hashes,
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
            metadata={
                "database": db["name"],
                "bot_dir": str(bot_dir),
                "created_utc": manifest["created_utc"],
            },
        )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
