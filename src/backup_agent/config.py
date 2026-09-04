from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:  # Python 3.11+
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # Python 3.9/3.10
    import tomli as tomllib  # type: ignore[no-redef]


class ConfigError(RuntimeError):
    pass


def load_config(path: str | os.PathLike[str]) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.is_file():
        raise ConfigError(f"Config file not found: {config_path}")

    with config_path.open("rb") as fh:
        data = tomllib.load(fh)

    agent = data.get("agent")
    telegram = data.get("telegram")
    jobs = data.get("jobs")

    if not isinstance(agent, dict):
        raise ConfigError("Missing [agent] section")
    if not isinstance(telegram, dict):
        raise ConfigError("Missing [telegram] section")
    if not isinstance(jobs, list) or not jobs:
        raise ConfigError("At least one [[jobs]] entry is required")

    for field in ("server_name", "work_dir"):
        if not agent.get(field):
            raise ConfigError(f"agent.{field} is required")

    names: set[str] = set()
    for job in jobs:
        if not isinstance(job, dict):
            raise ConfigError("Every [[jobs]] entry must be a table")
        name = str(job.get("name", "")).strip()
        job_type = str(job.get("type", "")).strip()
        if not name or not job_type:
            raise ConfigError("Each job requires name and type")
        if name in names:
            raise ConfigError(f"Duplicate job name: {name}")
        names.add(name)

    return data


def telegram_credentials(config: dict[str, Any]) -> tuple[str, str]:
    tg = config["telegram"]
    token_env = str(tg.get("bot_token_env", "BACKUP_TELEGRAM_BOT_TOKEN"))
    chat_env = str(tg.get("chat_id_env", "BACKUP_TELEGRAM_CHAT_ID"))

    token = os.environ.get(token_env, "").strip()
    chat_id = os.environ.get(chat_env, "").strip()

    if not token:
        raise ConfigError(f"Telegram bot token is missing from environment: {token_env}")
    if not chat_id:
        raise ConfigError(f"Telegram chat ID is missing from environment: {chat_env}")

    return token, chat_id
