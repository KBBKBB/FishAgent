"""CR-03 pilot access control (inert unless FISHAGENT_PUBLIC_ACCESS_ENABLED=true)."""

from __future__ import annotations

from fishagent.config import Settings, get_settings
from fishagent.pilot.state import PilotState

_state: PilotState | None = None


def get_pilot_state(settings: Settings | None = None) -> PilotState | None:
    """Return the process-wide pilot state, or None when the feature is off."""
    global _state
    resolved = settings or get_settings()
    if not resolved.public_access_enabled:
        return None
    if _state is None:
        _state = PilotState.from_settings(resolved)
    return _state


def reset_pilot_state() -> None:
    """Test/ops hook: drop counters and signed-token configuration."""
    global _state
    _state = None
