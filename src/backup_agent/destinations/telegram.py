from __future__ import annotations

import time
from pathlib import Path

import requests


class TelegramError(RuntimeError):
    pass


class TelegramClient:
    def __init__(self, token: str, chat_id: str, timeout: int = 180) -> None:
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.chat_id = chat_id
        self.timeout = timeout

    @staticmethod
    def _rewind_files(files) -> None:
        if not files:
            return
        for value in files.values():
            stream = value[1] if isinstance(value, tuple) and len(value) > 1 else value
            if hasattr(stream, "seek"):
                stream.seek(0)

    def _request(self, method: str, *, data=None, files=None, retries: int = 3):
        last_error: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                self._rewind_files(files)
                response = requests.post(
                    f"{self.base_url}/{method}",
                    data=data,
                    files=files,
                    timeout=self.timeout,
                )
                payload = response.json() if response.content else {}
                if response.ok and payload.get("ok", False):
                    return payload
                description = payload.get("description") or response.text
                raise TelegramError(
                    f"Telegram {method} failed ({response.status_code}): {description}"
                )
            except (requests.RequestException, ValueError, TelegramError) as exc:
                last_error = exc
                if attempt >= retries:
                    break
                time.sleep(min(2 ** attempt, 8))
        raise TelegramError(str(last_error) if last_error else "Telegram request failed")

    def send_message(self, text: str) -> None:
        self._request(
            "sendMessage",
            data={
                "chat_id": self.chat_id,
                "text": text,
                "disable_web_page_preview": "true",
            },
        )

    def send_document(self, path: Path, caption: str = "") -> None:
        with path.open("rb") as fh:
            self._request(
                "sendDocument",
                data={"chat_id": self.chat_id, "caption": caption[:1024]},
                files={"document": (path.name, fh, "application/octet-stream")},
            )
