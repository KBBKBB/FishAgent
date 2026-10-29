"""Location picker: name search and nearby-water listing.

Step 1 used to be a pair of lat/lon boxes. These endpoints back the two paths
that replaced it — typing a place you know, or picking from what is around you.
"""

from __future__ import annotations

import pytest
from conftest import HANGZHOU


@pytest.fixture()
def override_geo_provider():
    from fishagent.deps import get_geo_provider
    from fishagent.main import app

    def install(provider):
        app.dependency_overrides[get_geo_provider] = lambda: provider

    yield install
    app.dependency_overrides.pop(get_geo_provider, None)


def search(client, query):
    return client.get("/api/geo/search", params={"q": query})


def nearby(client, **overrides):
    params = dict(HANGZHOU)
    params.update(overrides)
    return client.get("/api/geo/nearby", params=params)


def test_search_returns_places_with_wgs84_coordinates(client):
    response = search(client, "青山水库")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["results"], "mock provider should resolve a known demo spot"
    place = payload["results"][0]
    assert place["name"]
    # The API accepts WGS84 everywhere; a picker that returned GCJ-02 would put
    # the user a few hundred metres off without anyone noticing.
    assert -90 <= place["lat"] <= 90
    assert -180 <= place["lon"] <= 180
    assert payload["resolved"] is True


def test_search_result_feeds_straight_back_into_the_analyzer(client):
    """The picker exists to produce an input the rest of the API accepts."""
    place = search(client, "青山水库").json()["results"][0]
    response = client.get(
        "/api/fish-activity", params={"lat": place["lat"], "lon": place["lon"]}
    )
    assert response.status_code == 200, response.text


def test_unknown_place_is_empty_but_not_an_error(client):
    response = search(client, "这个名字不太可能存在zzz")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert isinstance(payload["results"], list)
    # resolved=True means "we looked"; an empty list is a normal outcome and the
    # UI can say "not found" rather than "search is broken".
    assert payload["resolved"] is True


def test_blank_query_is_rejected_by_validation(client):
    response = client.get("/api/geo/search", params={"q": " "})
    # Whitespace passes min_length, so the route strips it and answers empty
    # rather than 422 — a search box that 500s on a trailing space is a bug.
    assert response.status_code == 200, response.text
    assert response.json()["results"] == []


def test_missing_query_is_a_validation_error(client):
    response = client.get("/api/geo/search")
    assert response.status_code == 422, response.text


def test_overlong_query_is_rejected(client):
    response = search(client, "湖" * 200)
    assert response.status_code == 422, response.text


def test_nearby_lists_water_with_distance(client):
    response = nearby(client)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["results"], "mock provider should find demo water nearby"
    place = payload["results"][0]
    assert place["name"]
    assert place["kind"] in {"湖泊", "河流", "水库", "野塘", "水域"}
    assert place["distance_m"] is not None and place["distance_m"] >= 0


def test_nearby_results_are_sorted_by_distance(client):
    places = nearby(client, limit=8).json()["results"]
    distances = [item["distance_m"] for item in places]
    assert distances == sorted(distances)


def test_nearby_respects_the_limit(client):
    payload = nearby(client, limit=2).json()
    assert len(payload["results"]) <= 2


def test_nearby_rejects_impossible_coordinates(client):
    response = client.get("/api/geo/nearby", params={"lat": 999, "lon": 0})
    assert response.status_code == 422, response.text


def test_nearby_honours_a_small_radius(client):
    """A 1 km radius must not quietly become the default 30 km."""
    response = nearby(client, radius_km=1)
    assert response.status_code == 200, response.text
    for place in response.json()["results"]:
        assert place["distance_m"] <= 1000


def test_provider_without_search_reports_unresolved(client, override_geo_provider):
    """A provider that cannot search must not look like 'place not found'."""

    class _NoPicker:
        async def find_water_spots(self, origin, center, radius_m):
            return []

        async def estimate_drive_seconds(self, *args, **kwargs):
            return 0

    override_geo_provider(_NoPicker())
    payload = search(client, "青山水库").json()
    assert payload["results"] == []
    assert payload["resolved"] is False


def test_provider_failure_degrades_to_empty_not_5xx(client, override_geo_provider):
    from fishagent.providers.base import ProviderError

    class _Broken:
        async def find_water_spots(self, origin, center, radius_m):
            return []

        async def estimate_drive_seconds(self, *args, **kwargs):
            return 0

        async def search_places(self, keyword, *, limit=8):
            raise ProviderError("upstream down")

        async def nearby_water(self, origin, *, radius_m=30_000, limit=8):
            raise ProviderError("upstream down")

    override_geo_provider(_Broken())
    # The manual coordinate form still works, so a picker outage must not take
    # the page down with a 5xx.
    search_response = search(client, "青山水库")
    assert search_response.status_code == 200, search_response.text
    assert search_response.json()["results"] == []
    nearby_response = nearby(client)
    assert nearby_response.status_code == 200, nearby_response.text
    assert nearby_response.json()["results"] == []


def test_unexpected_exception_does_not_escape(client, override_geo_provider):
    class _Exploding:
        async def find_water_spots(self, origin, center, radius_m):
            return []

        async def estimate_drive_seconds(self, *args, **kwargs):
            return 0

        async def search_places(self, keyword, *, limit=8):
            raise RuntimeError("boom")

    override_geo_provider(_Exploding())
    response = search(client, "青山水库")
    assert response.status_code == 200, response.text
    assert response.json()["results"] == []


def test_results_are_capped_at_the_requested_limit(client):
    payload = search(client, "青山").json()
    assert len(payload["results"]) <= 8


def test_failed_lookup_is_not_reported_as_no_water(client, override_geo_provider):
    """'We could not ask' and 'there is nothing here' must stay distinguishable."""
    from fishagent.providers.base import ProviderError

    class _Broken:
        async def find_water_spots(self, origin, center, radius_m):
            return []

        async def estimate_drive_seconds(self, *args, **kwargs):
            return 0

        async def nearby_water(self, origin, *, radius_m=30_000, limit=8):
            raise ProviderError("upstream down")

    override_geo_provider(_Broken())
    payload = nearby(client).json()
    assert payload["results"] == []
    assert payload["resolved"] is False


def _search_with_transport(provider, keyword, handler, monkeypatch):
    """Run a provider search against a stub transport.

    ``monkeypatch`` restores ``httpx.AsyncClient`` even if the search raises,
    which a hand-rolled try/finally does not guarantee on a failing assertion.
    """
    import asyncio

    import httpx

    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched)
    return asyncio.run(provider.search_places(keyword))


def test_water_is_ranked_before_other_matches(monkeypatch):
    """A search for a lake must not lead with a toll gate."""
    import httpx

    from fishagent.providers.amap import AMapGeoProvider

    pois = [
        {
            "name": "三岔湖收费站(SA2成都第二绕城高速出口)",
            "typecode": "180300",
            "location": "104.270000,30.290000",
            "address": "简阳市",
        },
        {
            "name": "三岔湖景区",
            # The real code from /v3/place/text: a coarse category prefix, not
            # the leaf 110202 that around-search returns.
            "typecode": "110200",
            "location": "104.266000,30.279000",
            "address": "望湖北街178号",
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "1", "info": "OK", "pois": pois})

    provider = AMapGeoProvider(api_key="test", qps=1000)
    results = _search_with_transport(provider, "三岔湖", handler, monkeypatch)
    assert [item.name for item in results][0].startswith("三岔湖景区")
    assert results[0].kind in {"湖泊", "河流", "水库", "野塘", "水域"}


def test_search_results_are_wgs84_not_gcj02(monkeypatch):
    """A GCJ-02 leak would put the user a few hundred metres off silently."""
    import httpx

    from fishagent.core.coords import wgs84_to_gcj02
    from fishagent.providers.amap import AMapGeoProvider

    # AMap would report this point in GCJ-02; the provider must hand back the
    # WGS84 value that came in.
    true_lat, true_lon = 30.2794, 104.2669
    gcj = wgs84_to_gcj02(true_lat, true_lon)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "1",
                "pois": [
                    {
                        "name": "三岔湖",
                        "typecode": "190205",
                        "location": f"{gcj.lon:.6f},{gcj.lat:.6f}",
                    }
                ],
            },
        )

    provider = AMapGeoProvider(api_key="test", qps=1000)
    result = _search_with_transport(provider, "三岔湖", handler, monkeypatch)[0]
    assert abs(result.lat - true_lat) < 0.002
    assert abs(result.lon - true_lon) < 0.002


def test_water_place_classifier_matches_text_search_codes():
    """Text search reports category prefixes; the strict around-search test
    matched none of them, so the ranking quietly did nothing in production."""
    from fishagent.providers.amap import _is_water_place

    # Real codes observed from /v3/place/text on 2026-10-29.
    assert _is_water_place("三岔湖景区", "110200")
    assert _is_water_place("三岔水库", "110203")
    assert _is_water_place("三岔湖景区-月亮岛", "110000")
    # Matches by name, but not somewhere you can start fishing from.
    assert not _is_water_place("三岔湖大桥", "190307")
    assert not _is_water_place("三岔湖收费站(SA2成都第二绕城高速出口)", "180200")
    assert not _is_water_place("三岔湖环球融创天堂洲际酒店(暂停营业)", "100102")
    assert not _is_water_place("三岔湖·天澜居", "100000")
