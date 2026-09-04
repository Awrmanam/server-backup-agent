from pathlib import Path

from backup_agent.config import load_config


def test_load_minimal_config(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        """
[agent]
server_name = "test"
work_dir = "/tmp/backups"

[telegram]
bot_token_env = "BOT_TOKEN"
chat_id_env = "CHAT_ID"

[[jobs]]
name = "files"
type = "files"
enabled = true
paths = ["/tmp"]
""".strip()
        + "\n",
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg["agent"]["server_name"] == "test"
    assert cfg["jobs"][0]["name"] == "files"
