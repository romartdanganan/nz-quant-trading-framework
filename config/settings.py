"""Loads .env secrets and config.yaml into a single Settings object used across the app."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@dataclass
class Settings:
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, config_path: Path | None = None) -> "Settings":
        config_path = config_path or ROOT_DIR / "config.yaml"
        return cls(raw=_load_yaml(config_path))

    def get(self, dotted_key: str, default: Any = None) -> Any:
        node: Any = self.raw
        for part in dotted_key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    @property
    def base_currency(self) -> str:
        return self.get("base_currency", "NZD")

    @property
    def env(self) -> str:
        return os.getenv("APP_ENV", "development")


def get_env(key: str, default: str | None = None) -> str | None:
    return os.getenv(key, default)


settings = Settings.load()
