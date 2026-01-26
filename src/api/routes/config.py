"""
Configuration API endpoints.

GET /api/config - Get current configuration
PUT /api/config - Update configuration and save to YAML
"""

from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

CONFIG_PATH = Path(__file__).parent.parent.parent.parent / "config" / "default.yaml"


class ConfigUpdate(BaseModel):
    """Request body for config updates"""
    config: dict[str, Any]


def load_config() -> dict:
    """Load config from YAML file"""
    if not CONFIG_PATH.exists():
        return {}
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f) or {}


def save_config(config: dict) -> None:
    """Save config to YAML file"""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)


@router.get("/config")
async def get_config() -> dict:
    """Get current configuration"""
    try:
        config = load_config()
        return {"config": config}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/config")
async def update_config(update: ConfigUpdate) -> dict:
    """Update configuration and save to YAML"""
    try:
        # Load current config
        current = load_config()

        # Deep merge with update
        def deep_merge(base: dict, update: dict) -> dict:
            result = base.copy()
            for key, value in update.items():
                if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                    result[key] = deep_merge(result[key], value)
                else:
                    result[key] = value
            return result

        merged = deep_merge(current, update.config)

        # Save
        save_config(merged)

        return {"status": "ok", "config": merged}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
