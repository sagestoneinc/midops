# ============================================================
# MID Ops Report Bot — Routing State Manager
# ============================================================
# Tracks current pool weights, active MIDs, and recent changes.
# Persisted to routing_state.json so it survives bot restarts.

import json
import os
from datetime import datetime

STATE_FILE = os.path.join(os.path.dirname(__file__), "routing_state.json")

DEFAULT_STATE = {
    "visa": {
        "pool_id": 154,
        "active_mids": {
            "TY_529": 20,
            "TY_530": 20,
            "TY_531": 40,
            "TY_534": 20
        },
        "recent_changes": "TY_523 switched off, TY_531 weight increased to 40%"
    },
    "mc": {
        "pool_id": 155,
        "active_mids": {
            "TY_522_V2": 20,
            "TY_529_v2": 20,
            "TY_533_v2": 20,
            "TY_534_v2": 40
        },
        "recent_changes": "TY_532_v2 switched off, TY_534_v2 weight increased to 40%"
    },
    "xshield": {
        "pool_id": 4,
        "active_mid": "TY_6_Xshield",
        "recent_changes": "None"
    },
    "last_updated": None
}


def load_state():
    """Load routing state from JSON file, or return defaults."""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return DEFAULT_STATE.copy()


def save_state(state):
    """Save routing state to JSON file."""
    state["last_updated"] = datetime.now().isoformat()
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def format_active_mids(brand: str, state: dict) -> str:
    """Format active MIDs string for report output."""
    if brand == "xshield":
        return f"**Active MID:** {state['xshield']['active_mid']} (single MID)"

    pool = state[brand]
    parts = [f"{mid} — {weight}%" for mid, weight in pool["active_mids"].items()]
    return f"**Active MIDs:** {', '.join(parts)}"


def format_recent_changes(brand: str, state: dict) -> str:
    """Format recent changes string for report output."""
    if brand == "xshield":
        changes = state["xshield"]["recent_changes"]
    else:
        changes = state[brand]["recent_changes"]
    return f"**Recent Changes:** {changes}"


def get_active_mid_names(brand: str, state: dict) -> list:
    """Get list of active MID name prefixes for bolding in tables."""
    if brand == "xshield":
        return [state["xshield"]["active_mid"]]
    return list(state[brand]["active_mids"].keys())


def update_visa_routing(state: dict, active_mids: dict, changes: str) -> dict:
    """Update Visa pool routing."""
    state["visa"]["active_mids"] = active_mids
    state["visa"]["recent_changes"] = changes
    save_state(state)
    return state


def update_mc_routing(state: dict, active_mids: dict, changes: str) -> dict:
    """Update MC pool routing."""
    state["mc"]["active_mids"] = active_mids
    state["mc"]["recent_changes"] = changes
    save_state(state)
    return state


def update_xshield_changes(state: dict, changes: str) -> dict:
    """Update xShield recent changes."""
    state["xshield"]["recent_changes"] = changes
    save_state(state)
    return state


def clear_recent_changes(state: dict) -> dict:
    """Clear all recent changes to 'None'."""
    state["visa"]["recent_changes"] = "None"
    state["mc"]["recent_changes"] = "None"
    state["xshield"]["recent_changes"] = "None"
    save_state(state)
    return state
