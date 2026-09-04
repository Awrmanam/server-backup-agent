# Server Backup Agent

A small, modular backup agent for Linux servers. It creates verified disaster-recovery archives and sends them to a private Telegram chat. The first job type is tailored for the Mirza bot; generic file backups can be added later without changing the core.

## What the Mirza job backs up

- Full MySQL/MariaDB database dump (users, orders, products, panels, bot settings, premium emoji IDs and other runtime data stored in DB)
- Complete bot directory, including local runtime files and `config.php`
- Root crontab
- Optional server configuration paths such as Nginx, PHP-FPM, systemd, cron.d and Let's Encrypt
- Installed package list and PHP module list
- Manifest and SHA-256 integrity metadata

The resulting archive can be encrypted with `age`, split into Telegram-safe parts, uploaded, and locally retained for a configurable number of days.

## Security model

**Do not commit secrets or backups to GitHub.** Telegram bot token/chat ID live only in `/etc/server-backup-agent/secrets.env`, which is never part of the repository. Backup archives can contain bot tokens, database passwords and user data, so enabling `age` encryption is strongly recommended before production use.

## Quick install

Because this repository is private, clone it using an authenticated GitHub method (SSH, GitHub CLI, or a token):

```bash
git clone https://github.com/Awrmanam/server-backup-agent.git /opt/server-backup-agent
cd /opt/server-backup-agent
sudo bash install.sh
```

Edit the runtime configuration:

```bash
sudo nano /etc/server-backup-agent/config.toml
sudo nano /etc/server-backup-agent/secrets.env
```

For the current Hong Kong Mirza installation, the example config already uses:

```text
/var/www/html/mirzaprobotconfig
/var/www/html/mirzaprobotconfig/config.php
```

Put the Telegram secrets in `/etc/server-backup-agent/secrets.env`:

```bash
BACKUP_TELEGRAM_BOT_TOKEN=123456:ABCDEF...
BACKUP_TELEGRAM_CHAT_ID=123456789
```

Lock the file down:

```bash
sudo chmod 600 /etc/server-backup-agent/secrets.env
```

## Test Telegram first

```bash
sudo /opt/server-backup-agent/.venv/bin/server-backup-agent \
  --config /etc/server-backup-agent/config.toml \
  --test-telegram
```

## Run one Mirza backup manually

```bash
sudo /opt/server-backup-agent/.venv/bin/server-backup-agent \
  --config /etc/server-backup-agent/config.toml \
  --job mirza-hk
```

## Automatic schedule

The included systemd timer runs every 6 hours with a small offset. Enable it with:

```bash
sudo systemctl enable --now server-backup-agent.timer
systemctl list-timers server-backup-agent.timer
```

Logs:

```bash
journalctl -u server-backup-agent.service -n 100 --no-pager
```

## Encryption with age

Install `age` and generate a key on a trusted machine (preferably your own laptop, not the server):

```bash
age-keygen -o backup-age-key.txt
```

Copy only the **public recipient** (starts with `age1...`) into `config.toml`:

```toml
[agent.encryption]
enabled = true
recipient = "age1..."
```

Keep `backup-age-key.txt` offline/private. The server needs only the public recipient.

Decrypt a downloaded backup:

```bash
age -d -i backup-age-key.txt -o backup.tar.gz backup.tar.gz.age
```

## Split backup restoration

If Telegram received multiple parts, concatenate them in lexical order first:

```bash
cat backup.tar.gz.age.part-* > backup.tar.gz.age
```

Then decrypt (if enabled) and verify against the SHA-256 value sent in the Telegram summary.

## Restore helper

A guarded Mirza restore helper is included at:

```text
restore/mirza_restore.sh
```

It does not overwrite a live installation without explicit flags. Read the script usage before restoring.

## Adding future backups

Add another `[[jobs]]` entry in `/etc/server-backup-agent/config.toml`. The project is intentionally structured so Rebecca, other databases and arbitrary directories can be added as new job modules/destinations without changing Telegram handling.
