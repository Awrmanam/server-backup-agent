from __future__ import annotations

import argparse
import fcntl
import logging
import os
import socket
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backup_agent.config import ConfigError, load_config, telegram_credentials
from backup_agent.destinations.telegram import TelegramClient
from backup_agent.jobs.files import create_files_backup
from backup_agent.jobs.mirza import create_mirza_backup
from backup_agent.util import (
    cleanup_parts,
    human_size,
    remove_old_files,
    require_command,
    run,
    sha256_file,
    split_file,
)

LOG = logging.getLogger("server-backup-agent")


def _encrypt(path: Path, encryption: dict[str, Any]) -> Path:
    if not bool(encryption.get("enabled", False)):
        return path

    recipient = str(encryption.get("recipient", "")).strip()
    if not recipient:
        raise RuntimeError("Encryption is enabled but agent.encryption.recipient is empty")

    require_command("age")
    encrypted = path.with_name(path.name + ".age")
    run(["age", "-r", recipient, "-o", str(encrypted), str(path)])
    os.chmod(encrypted, 0o600)

    if bool(encryption.get("delete_plain_after_encrypt", True)):
        path.unlink(missing_ok=True)
    return encrypted


def _make_checksum_file(path: Path, digest: str) -> Path:
    checksum = path.with_name(path.name + ".sha256")
    checksum.write_text(f"{digest}  {path.name}\n", encoding="utf-8")
    os.chmod(checksum, 0o600)
    return checksum


def _build_job(job: dict[str, Any], agent: dict[str, Any]):
    job_type = str(job["type"]).lower()
    if job_type == "mirza":
        return create_mirza_backup(job, agent)
    if job_type == "files":
        return create_files_backup(job, agent)
    raise RuntimeError(f"Unsupported job type: {job_type}")


def _selected_jobs(config: dict[str, Any], requested: str | None) -> list[dict[str, Any]]:
    enabled = [job for job in config["jobs"] if bool(job.get("enabled", True))]
    if requested is None:
        return enabled
    selected = [job for job in enabled if str(job.get("name")) == requested]
    if not selected:
        raise RuntimeError(f"Enabled job not found: {requested}")
    return selected


def _summary(
    *,
    server_name: str,
    job_name: str,
    payload: Path,
    digest: str,
    part_count: int,
    encrypted: bool,
) -> str:
    state = "encrypted" if encrypted else "PLAINTEXT"
    return (
        "✅ Backup completed\n"
        f"Server: {server_name}\n"
        f"Job: {job_name}\n"
        f"File: {payload.name}\n"
        f"Size: {human_size(payload.stat().st_size)}\n"
        f"Parts: {part_count}\n"
        f"Mode: {state}\n"
        f"SHA256: {digest}\n"
        f"UTC: {datetime.now(timezone.utc).isoformat(timespec='seconds')}"
    )


def _run_one(
    job: dict[str, Any],
    config: dict[str, Any],
    telegram: TelegramClient,
) -> None:
    agent = config["agent"]
    server_name = str(agent.get("server_name") or socket.gethostname())
    job_name = str(job["name"])
    LOG.info("Starting backup job %s", job_name)

    artifact = _build_job(job, agent)
    encryption = dict(agent.get("encryption") or {})
    payload = _encrypt(artifact.path, encryption)
    digest = sha256_file(payload)
    checksum_file = _make_checksum_file(payload, digest)

    split_mb = int(agent.get("split_mb", 45))
    if split_mb < 1:
        raise RuntimeError("agent.split_mb must be at least 1")
    parts = split_file(payload, split_mb * 1024 * 1024)

    try:
        total_parts = len(parts)
        for index, part in enumerate(parts, start=1):
            caption = (
                f"🗄 {server_name} / {job_name}\n"
                f"Part {index}/{total_parts}\n"
                f"{part.name}"
            )
            telegram.send_document(part, caption)

        telegram.send_document(checksum_file, f"SHA256 / {server_name} / {job_name}")
        telegram.send_message(
            _summary(
                server_name=server_name,
                job_name=job_name,
                payload=payload,
                digest=digest,
                part_count=total_parts,
                encrypted=bool(encryption.get("enabled", False)),
            )
        )
    finally:
        cleanup_parts(parts, payload)

    retention_days = int(agent.get("retention_days", 14))
    removed = remove_old_files(Path(str(agent["work_dir"])), retention_days)
    LOG.info("Completed backup job %s; removed %d expired local files", job_name, removed)


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def cli() -> int:
    parser = argparse.ArgumentParser(description="Server Backup Agent")
    parser.add_argument(
        "--config",
        default="/etc/server-backup-agent/config.toml",
        help="Path to runtime TOML config",
    )
    parser.add_argument("--job", help="Run only one enabled job by name")
    parser.add_argument("--test-telegram", action="store_true", help="Send a test message and exit")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    _configure_logging(args.verbose)

    try:
        config = load_config(args.config)
        token, chat_id = telegram_credentials(config)
        timeout = int(config["telegram"].get("request_timeout_seconds", 180))
        telegram = TelegramClient(token, chat_id, timeout=timeout)
        server_name = str(config["agent"].get("server_name") or socket.gethostname())

        if args.test_telegram:
            telegram.send_message(f"✅ Server Backup Agent connected\nServer: {server_name}")
            print("Telegram test message sent successfully")
            return 0

        lock_path = Path(str(config["agent"].get("lock_file", "/run/lock/server-backup-agent.lock")))
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_handle = lock_path.open("w")
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            LOG.warning("Another backup run is already active; exiting")
            return 0

        failures = 0
        for job in _selected_jobs(config, args.job):
            try:
                _run_one(job, config, telegram)
            except Exception as exc:
                failures += 1
                LOG.exception("Backup job %s failed", job.get("name"))
                try:
                    telegram.send_message(
                        "❌ Backup failed\n"
                        f"Server: {server_name}\n"
                        f"Job: {job.get('name')}\n"
                        f"Error: {str(exc)[:1200]}"
                    )
                except Exception:
                    LOG.exception("Could not send Telegram failure notification")

        return 1 if failures else 0

    except (ConfigError, RuntimeError, OSError) as exc:
        LOG.error("Fatal error: %s", exc)
        if args.verbose:
            traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(cli())
