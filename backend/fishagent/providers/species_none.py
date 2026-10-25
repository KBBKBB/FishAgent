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

    async def find_species(
        self,
        spots: list[SpotSpeciesQuery],
    ) -> list[list[str]]:
        return [[] for _ in spots]
