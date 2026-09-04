from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class BackupArtifact:
    job_name: str
    path: Path
    metadata: dict[str, Any] = field(default_factory=dict)
