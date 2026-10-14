"""
Reads the YAML files in the config/ folder.

    config.load("sources")   ->  contents of config/sources.yaml
    config.load("keywords")  ->  contents of config/keywords.yaml
"""

from functools import lru_cache
from pathlib import Path

import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


@lru_cache(maxsize=None)   # read each file only once per run
def load(name):
    with open(CONFIG_DIR / f"{name}.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)
