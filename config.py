import json
import os
from typing import Dict, Any

DEFAULT_CONFIG = {
    "colors": {
        "working": {
            "mode": 1,         # 1 = Breathing
            "rgb": [255, 0, 0],   # Pure Red (255, 0, 0)
            "speed": 1         # 0 = Slow, 1 = Normal, 2 = Fast
        },
        "waiting_approval": {
            "mode": 0,         # 0 = Static Solid
            "rgb": [255, 255, 0], # Pure Yellow (255, 255, 0)
            "speed": 1
        },
        "default_idle": {
            "mode": 0,         # 0 = Static Solid
            "rgb": [0, 220, 255], # Calm Cyan / User Default
            "speed": 1
        }
    },
    "timings": {
        "active_poll_interval_sec": 0.35,
        "dormant_poll_interval_sec": 2.5
    },
    "priority": "waiting_first", # "waiting_first": WAITING > WORKING > IDLE
    "autostart": False
}

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

def load_config() -> Dict[str, Any]:
    if not os.path.exists(CONFIG_FILE):
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                if k not in data:
                    data[k] = v
            return data
    except Exception as e:
        print(f"Error loading config, using defaults: {e}")
        return DEFAULT_CONFIG.copy()

def save_config(cfg: Dict[str, Any]) -> None:
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4)
    except Exception as e:
        print(f"Error saving config: {e}")
