from pathlib import Path

import yaml
from pydantic import BaseModel


class ProfileConfig(BaseModel):
    name: str
    aliases: list[str] = []
    currency: str = "USD"
    language: str = "ru"
    categories: dict = {}
    reports: list[dict] = []
    metrics: list[dict] = []
    special_features: dict = {}
    tax: dict | None = None


class ProfileLoader:
    """Loads YAML profiles from config/profiles/."""

    def __init__(self, profiles_dir: str = "config/profiles"):
        self._profiles: dict[str, ProfileConfig] = {}
        self._load_all(profiles_dir)

    def _load_all(self, dir_path: str) -> None:
        profiles_path = Path(dir_path)
        if not profiles_path.exists():
            return
        for yaml_file in profiles_path.glob("*.yaml"):
            if yaml_file.name.startswith("_"):
                continue
            with open(yaml_file, encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if data:
                    profile = ProfileConfig(**data)
                    self._profiles[yaml_file.stem] = profile

    def match(self, user_description: str) -> ProfileConfig | None:
        """Find profile by user description (aliases)."""
        desc = user_description.lower()
        for profile in self._profiles.values():
            if any(alias in desc for alias in profile.aliases):
                return profile
        return None

    def get(self, name: str | None) -> ProfileConfig | None:
        if name is None:
            return None
        return self._profiles.get(name)

    def all_profiles(self) -> list[ProfileConfig]:
        return list(self._profiles.values())
