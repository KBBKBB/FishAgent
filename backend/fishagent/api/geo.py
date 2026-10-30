"""Location picker: resolve a place name, or list water bodies nearby.

Most anglers know where they are going by name ("青龙湖"), not by coordinates.
These two endpoints exist so Step 1 does not put a lat/lon pair in front of
them; the manual coordinate form stays available but is no longer the only way
in.

Both degrade to an empty list rather than failing the request. A picker with no
results is a normal state (the name may be unknown, the area may have no
mapped water); the manual form still works, so a 5xx here would break a page
that has a perfectly good fallback.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query

from fishagent.deps import get_geo_provider
from fishagent.providers.base import GeoProvider, ProviderError
from fishagent.schemas import LatLon, PlaceCandidate, PlaceSearchResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/geo", tags=["geo"])

_MAX_RESULTS = 8
# Big enough to cover "the lakes I can drive to", small enough that the list
# stays something you can scan on a phone.
_NEARBY_RADIUS_M = 30_000
_QUERY_MAX_LENGTH = 60


@router.get("/search", response_model=PlaceSearchResponse)
async def search_places(
    q: str = Query(..., min_length=1, max_length=_QUERY_MAX_LENGTH),
    limit: int = Query(default=_MAX_RESULTS, ge=1, le=20),
    geo_provider: GeoProvider = Depends(get_geo_provider),
) -> PlaceSearchResponse:
    keyword = q.strip()
    if not keyword:
        return PlaceSearchResponse(results=[], query=q, resolved=False)
    search = getattr(geo_provider, "search_places", None)
    if search is None:
        # Provider cannot resolve names; the client falls back to the manual form.
        logger.info("geo provider does not support name search")
        return PlaceSearchResponse(results=[], query=keyword, resolved=False)
    try:
        results = await search(keyword, limit=limit)
    except ProviderError:
        logger.warning("place search failed for %r", keyword, exc_info=True)
        results = []
    except Exception:  # noqa: BLE001 - a picker must never take the page down
        logger.warning("place search raised for %r", keyword, exc_info=True)
        results = []
    cleaned = [item for item in results if _usable(item)][:limit]
    return PlaceSearchResponse(
        results=cleaned,
        query=keyword,
        # ``resolved`` distinguishes "we searched and found nothing" from
        # "this provider cannot search", so the UI can word the empty state.
        resolved=search is not None,
    )


@router.get("/nearby", response_model=PlaceSearchResponse)
async def nearby_water(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(default=_NEARBY_RADIUS_M / 1000, ge=1, le=50),
    limit: int = Query(default=_MAX_RESULTS, ge=1, le=20),
    geo_provider: GeoProvider = Depends(get_geo_provider),
) -> PlaceSearchResponse:
    nearby = getattr(geo_provider, "nearby_water", None)
    if nearby is None:
        logger.info("geo provider does not support nearby water")
        return PlaceSearchResponse(results=[], query="", resolved=False)
    try:
        results = await nearby(
            LatLon(lat=lat, lon=lon), radius_m=int(radius_km * 1000), limit=limit
        )
    except ProviderError:
        logger.warning("nearby water failed", exc_info=True)
        results = []
        # A failed lookup is not "there is no water here"; saying so would send
        # the user looking for a lake that the service simply could not query.
        return PlaceSearchResponse(results=[], query="", resolved=False)
    except Exception:  # noqa: BLE001
        logger.warning("nearby water raised", exc_info=True)
        return PlaceSearchResponse(results=[], query="", resolved=False)
    return PlaceSearchResponse(
        results=[item for item in results if _usable(item)][:limit],
        query="",
        resolved=True,
    )


def _usable(item: PlaceCandidate) -> bool:
    """A picker entry needs a name and somewhere to point at."""
    if not isinstance(item, PlaceCandidate):
        return False
    if not item.name.strip():
        return False
    return -90 <= item.lat <= 90 and -180 <= item.lon <= 180  # noqa: SIM103
