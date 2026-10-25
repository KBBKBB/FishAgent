"""Species normalisation shared by the mock and future community providers.

Community posts mention species in many forms; the API only returns a bounded,
deduplicated list of recognised names so the UI stays predictable.
"""

from __future__ import annotations

from collections.abc import Iterable

# Broader than the four species accepted by the activity calculator: spot
# recommendations describe what anglers actually report catching there.
KNOWN_SPECIES = (
    "鲫鱼",
    "鲤鱼",
    "草鱼",
    "鲢鳙",
    "青鱼",
    "鳊鱼",
    "黑鱼",
    "翘嘴",
    "鲈鱼",
    "罗非鱼",
    "黄颡鱼",
    "鲶鱼",
    "白条",
    "马口",
    "鳜鱼",
    "鲴鱼",
)

SPECIES_ALIASES = (
    ("胖头鱼", "鲢鳙"),
    ("胖头", "鲢鳙"),
    ("花鲢", "鲢鳙"),
    ("大头鱼", "鲢鳙"),
    ("武昌鱼", "鳊鱼"),
    ("翘嘴鲌", "翘嘴"),
    ("黄骨鱼", "黄颡鱼"),
    ("黄辣丁", "黄颡鱼"),
    ("昂刺鱼", "黄颡鱼"),
    ("乌鳢", "黑鱼"),
    ("鲫", "鲫鱼"),
    ("鲤", "鲤鱼"),
)

DEFAULT_MAX_SPECIES = 4


def _canonical(value: str) -> str | None:
    if value in KNOWN_SPECIES:
        return value
    for alias, species in SPECIES_ALIASES:
        if alias in value:
            return species
    return None


def normalize_species(
    values: Iterable[object],
    limit: int = DEFAULT_MAX_SPECIES,
) -> list[str]:
    """Trim, alias-map, dedupe and cap a provider's raw species list."""
    seen: set[str] = set()
    result: list[str] = []
    for item in values:
        text = str(item or "").strip()
        if not text:
            continue
        species = _canonical(text)
        if species is None or species in seen:
            continue
        seen.add(species)
        result.append(species)
        if len(result) >= limit:
            break
    return result
