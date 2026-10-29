"""No-op species provider used when community lookup is not configured.

Real mode defaults here so the API never invents community data. A future
Xiaohongshu adapter implements `SpeciesProvider` and is selected through
`FISHAGENT_SPECIES_PROVIDER`.
"""

from __future__ import annotations

from fishagent.schemas import SpotSpeciesQuery


class NullSpeciesProvider:
    name = "none"
    source_label = ""
    # This provider never looked anything up, so an empty result from it says
    # nothing about the water body. Deriving a water-type fallback here would
    # invent a recommendation for a feature that is deliberately switched off.
    resolves_empty = False

    async def find_species(
        self,
        spots: list[SpotSpeciesQuery],
    ) -> list[list[str]]:
        return [[] for _ in spots]
