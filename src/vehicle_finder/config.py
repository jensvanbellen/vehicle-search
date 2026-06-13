"""Runtime settings, loaded from environment / .env (see .env.example).

Search targets, model-code maps, scoring weights and synonyms live in YAML under
``config/`` and are loaded separately (see :mod:`vehicle_finder.configio`). This module
only holds *runtime* settings (paths, HTTP politeness, feature flags).
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root = three levels up from this file (src/vehicle_finder/config.py).
REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Process-wide runtime settings."""

    model_config = SettingsConfigDict(
        env_prefix="VF_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Core
    db_path: Path = Field(default=Path("data/vehicles.db"))
    config_dir: Path = Field(default=Path("config"))
    home_postcode: str = Field(default="2548 AE")
    log_level: str = Field(default="INFO")
    log_json: bool = Field(default=False)

    # HTTP politeness — applied to every live fetch.
    http_timeout: float = Field(default=30.0)
    http_max_retries: int = Field(default=3)
    request_delay_seconds: float = Field(default=2.0)
    user_agent: str = Field(
        default="vehicle-finder/0.1 (personal use)",
    )

    # bmw.de live transport (Playwright). Off by default.
    bmwde_enabled: bool = Field(default=False)
    playwright_headless: bool = Field(default=False)

    # Notifications — never send unless explicitly enabled.
    notify_enabled: bool = Field(default=False)

    def resolve(self, p: Path) -> Path:
        """Resolve a possibly-relative path against the repo root."""
        return p if p.is_absolute() else (REPO_ROOT / p)

    @property
    def db_file(self) -> Path:
        return self.resolve(self.db_path)

    @property
    def config_path(self) -> Path:
        return self.resolve(self.config_dir)


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
