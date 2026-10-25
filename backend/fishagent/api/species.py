"""POST /api/spots/species — batch community species recommendations."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from fishagent.deps import get_species_provider
from fishagent.providers.base import SpeciesProvider
from fishagent.schemas import SpeciesQueryRequest, SpeciesRecommendationResponse
from fishagent.services import species as species_service

router = APIRouter(prefix="/api/spots", tags=["spots"])


@router.post("/species", response_model=SpeciesRecommendationResponse)
async def recommend_species(
    payload: SpeciesQueryRequest,
    provider: SpeciesProvider = Depends(get_species_provider),
) -> SpeciesRecommendationResponse:
    return await species_service.build_species_recommendations(provider, payload.spots)
