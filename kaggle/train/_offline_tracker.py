"""Offline experiment tracking.

The GPU notebook has no network, so hosted trackers are unavailable. This writes JSONL
metrics and a run summary next to the checkpoints; the run directory is the artifact.
"""

from __future__ import annotations

import json
import platform
import subprocess
import time
from pathlib import Path
from typing import Any


class OfflineTracker:
    """Filesystem-backed run logger."""

    def __init__(self, run_dir: Path, config: dict[str, Any]) -> None:
        self.run_dir = run_dir
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._metrics_path = self.run_dir / "metrics.jsonl"
        self._started = time.time()
        (self.run_dir / "config.json").write_text(json.dumps(config, indent=2, default=str))
        (self.run_dir / "environment.json").write_text(json.dumps(self._environment(), indent=2))

    def _environment(self) -> dict[str, Any]:
        """Captured so a checkpoint can be traced back to the exact stack that made it."""
        env: dict[str, Any] = {
            "python": platform.python_version(),
            "platform": platform.platform(),
        }
        try:
            import torch

            env["torch"] = torch.__version__
            env["cuda"] = torch.version.cuda
            env["gpu"] = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu"
        except ImportError:
            env["torch"] = None
        try:
            env["git_sha"] = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
            ).strip()
        except (subprocess.SubprocessError, FileNotFoundError):
            env["git_sha"] = None
        return env

    def log(self, step: int, **metrics: float) -> None:
        row = {"step": step, "elapsed_s": round(time.time() - self._started, 2), **metrics}
        with self._metrics_path.open("a") as handle:
            handle.write(json.dumps(row) + "\n")

    def summarise(self, **summary: Any) -> None:
        payload = {"duration_s": round(time.time() - self._started, 2), **summary}
        (self.run_dir / "summary.json").write_text(json.dumps(payload, indent=2, default=str))
