import os
from pathlib import Path
from typing import Optional, Dict
import yaml
from pydantic import BaseModel, Field


class FridayConfig(BaseModel):
    """FRIDAY workspace configuration and runtime settings."""

    model: str = "gemini/gemini-3.8-flash"
    temperature: float = 0.2
    max_context_tokens: int = 8192
    yolo_mode: bool = False
    verification_command: Optional[str] = None
    max_repair_retries: int = 3
    max_steps: int = 10
    api_base: Optional[str] = None
    active_profile: Optional[str] = None
    api_keys: Dict[str, str] = Field(default_factory=dict)
    telegram_enabled: bool = False
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None


def load_config(target_dir: Path) -> FridayConfig:
    """Load configuration from .friday/config.yaml in target workspace, falling back to defaults."""
    config_file = target_dir / ".friday" / "config.yaml"
    if not config_file.is_file():
        return FridayConfig()

    try:
        content = config_file.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
        if isinstance(data, dict):
            return FridayConfig(**data)
    except Exception:
        pass

    return FridayConfig()


def save_config(target_dir: Path, config: FridayConfig) -> Path:
    """Save configuration to .friday/config.yaml in target workspace."""
    config_dir = target_dir / ".friday"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "config.yaml"

    yaml_data = yaml.dump(config.model_dump(), sort_keys=False, default_flow_style=False)
    config_file.write_text(yaml_data, encoding="utf-8")
    return config_file


def save_env_key(target_dir: Path, key: str, value: str) -> Path:
    """Persist an environment variable key-value pair to .env in target workspace."""
    env_file = target_dir / ".env"
    lines: list[str] = []
    found = False
    if env_file.is_file():
        try:
            content = env_file.read_text(encoding="utf-8")
            for line in content.splitlines():
                stripped = line.strip()
                if stripped.startswith(f"{key}=") or stripped.startswith(f"{key} ="):
                    lines.append(f"{key}={value}")
                    found = True
                else:
                    lines.append(line)
        except Exception:
            pass

    if not found:
        lines.append(f"{key}={value}")

    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return env_file


def load_env_file(target_dir: Path) -> Dict[str, str]:
    """Read key-value pairs from .env in target workspace."""
    env_file = target_dir / ".env"
    result: Dict[str, str] = {}
    if not env_file.is_file():
        return result
    try:
        content = env_file.read_text(encoding="utf-8")
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                if k:
                    result[k] = v
    except Exception:
        pass
    return result


def sync_env_keys(target_dir: Path, config: FridayConfig) -> None:
    """Populate os.environ from workspace .env, home directories, and configured API keys."""
    # Check user home and .friday directories for global keys (e.g. GROQ_API_KEY)
    for home_candidate in [Path.home() / ".env", Path.home() / ".friday" / ".env"]:
        if home_candidate.is_file():
            global_vars = load_env_file(home_candidate.parent)
            for k, v in global_vars.items():
                if k not in os.environ:
                    os.environ[k] = v

    env_vars = load_env_file(target_dir)
    for k, v in env_vars.items():
        if k not in os.environ:
            os.environ[k] = v
    for k, v in config.api_keys.items():
        if k not in os.environ:
            os.environ[k] = v


