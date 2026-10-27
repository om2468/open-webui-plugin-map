import asyncio
import json
import socket
import urllib.error
import urllib.request
from pathlib import Path

import pytest

import tool
from tool import Tools

FIX = Path(__file__).parent / "fixtures"


def fixture_bytes(name):
    return (FIX / name).read_bytes()


@pytest.fixture
def valves():
    return Tools.Valves()


@pytest.fixture
def allow_valves():
    v = Tools.Valves()
    v.network_policy = "allowlist"
    v.allowed_hosts = "example.com, *.wild.org, tile.openstreetmap.org, unpkg.com"
    return v


def run(coro):
    return asyncio.run(coro)


def norm(raw, v):
    return tool._normalise_spec(raw, v)


# ---------------------------------------------------------------------------
# 1. _normalise_spec
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "alias,expected",
    [("tile", "xyz"), ("tiles", "xyz"), ("raster", "xyz"), ("tms", "xyz"),
     ("ogc-api", "ogcapi"), ("features", "ogcapi"), ("json", "geojson"), ("vector", "geojson"),
     ("mvt", "vectortiles"), ("geotiff", "cog"), ("tif", "cog"), ("3d-buildings", "buildings"),
     ("WMS", "wms"), (" XYZ ", "xyz")],
)
def test_type_aliases(valves, alias, expected):
    layer = {"type": alias, "url": "https://example.com/x", "data": {"type": "FeatureCollection", "features": []}}
    spec, _, rejected = norm({"layers": [layer]}, valves)
    assert not rejected
    assert spec["layers"][0]["type"] == expected


@pytest.mark.parametrize(
    "layer,expected",
    [
        ({"url": "https://e.com/a/{z}/{x}/{y}.png"}, "xyz"),
        ({"url": "https://e.com/data.geojson"}, "geojson"),
        ({"url": "https://e.com/data.json"}, "geojson"),
        ({"url": "https://e.com/x.pmtiles"}, "pmtiles"),
        ({"url": "https://e.com/x.tif"}, "cog"),
        ({"url": "https://e.com/x.TIFF?a=b"}, "cog"),
        ({"url": "https://e.com/t/{z}/{x}/{y}.pbf"}, "vectortiles"),
        ({"url": "https://e.com/ows?service=WMS&request=GetMap"}, "wms"),
        ({"url": "https://e.com/geoserver/wms", "layers": "a"}, "wms"),
        ({"url": "https://e.com/ows?service=WFS"}, "wfs"),
        ({"url": "https://e.com/ows", "typeName": "ns:a"}, "wfs"),
        ({"url": "https://e.com/ows?SERVICE=WMTS"}, "wmts"),
        ({"url": "https://e.com/wmts/{TileMatrix}/{TileCol}/{TileRow}.png"}, "wmts"),
        ({"url": "https://e.com/api/collections/lakes"}, "ogcapi"),
        ({"url": "https://e.com/pic.png"}, "image"),
        ({"data": {"type": "Point", "coordinates": [0, 0]}}, "geojson"),
    ],
)
def test_guess_type(valves, layer, expected):
    assert tool._guess_type(layer) == expected
    spec, _, rejected = norm({"layers": [layer]}, valves)
    assert not rejected
    assert spec["layers"][0]["type"] == expected


def test_guess_type_unknown_rejected(valves):
    assert tool._guess_type({"url": "https://e.com/mystery"}) == ""
    spec, _, rejected = norm({"layers": [{"url": "https://e.com/mystery"}]}, valves)
    assert spec["layers"] == []
    assert len(rejected) == 1 and "unknown type" in rejected[0]


def test_layers_as_json_string(valves):
    layers = json.dumps([{"type": "xyz", "url": "https://e.com/{z}/{x}/{y}.png", "name": "A"}])
    spec, warnings, rejected = norm({"layers": layers}, valves)
    assert [l["name"] for l in spec["layers"]] == ["A"]
    assert not warnings and not rejected


def test_layers_as_single_dict(valves):
    spec, _, _ = norm({"layers": {"type": "xyz", "url": "https://e.com/{z}/{x}/{y}.png"}}, valves)
    assert len(spec["layers"]) == 1


def test_layers_invalid_json_string_warns(valves):
    spec, warnings, _ = norm({"layers": "[not json"}, valves)
    assert spec["layers"] == []
    assert any("not valid JSON" in w for w in warnings)


def test_layer_item_as_json_string_and_non_object(valves):
    item = json.dumps({"type": "xyz", "url": "https://e.com/{z}/{x}/{y}.png"})
    spec, warnings, _ = norm({"layers": [item, 42]}, valves)
    assert len(spec["layers"]) == 1
    assert any("layers[1] is not an object" in w for w in warnings)


def test_style_and_data_strings_are_parsed(valves):
    layer = {"type": "geojson", "style": '{"color": "#f00"}',
             "data": '{"type":"FeatureCollection","features":[]}'}
    spec, _, _ = norm({"layers": [layer]}, valves)
    out = spec["layers"][0]
    assert out["style"] == {"color": "#f00"}
    assert out["data"]["type"] == "FeatureCollection"


def test_layer_default_names(valves):
    spec, _, _ = norm({"layers": [
        {"type": "wms", "url": "https://e.com/wms", "layers": "roads"},
        {"type": "xyz", "url": "https://e.com/{z}/{x}/{y}.png"},
    ]}, valves)
    assert spec["layers"][0]["name"] == "roads"
    assert spec["layers"][1]["name"] == "xyz 2"


def test_rejects_unknown_type(valves):
    spec, _, rejected = norm({"layers": [{"type": "hologram", "url": "https://e.com/x"}]}, valves)
    assert spec["layers"] == []
    assert "unknown type 'hologram'" in rejected[0]


def test_rejects_missing_url(valves):
    spec, _, rejected = norm({"layers": [{"type": "wms", "name": "W"}]}, valves)
    assert spec["layers"] == []
    assert "need a 'url'" in rejected[0]


def test_geojson_needs_data_or_url(valves):
    _, _, rejected = norm({"layers": [{"type": "geojson"}]}, valves)
    assert "need 'data' or 'url'" in rejected[0]


def test_buildings_needs_no_url(valves):
    spec, _, rejected = norm({"layers": [{"type": "buildings"}]}, valves)
    assert not rejected and spec["layers"][0]["type"] == "buildings"


def test_tiles_substitute_for_url(valves):
    spec, _, rejected = norm({"layers": [{"type": "vectortiles", "tiles": ["https://e.com/{z}/{x}/{y}.pbf"]}]}, valves)
    assert not rejected and len(spec["layers"]) == 1


@pytest.mark.parametrize("bad", ["javascript:alert(1)", "data:text/html,hi", "file:///etc/passwd", "ftp://e.com/x"])
def test_rejects_non_http_schemes(valves, bad):
    spec, _, rejected = norm({"layers": [{"type": "xyz", "url": bad}]}, valves)
    assert spec["layers"] == []
    assert "only http(s) or same-host" in rejected[0]


def test_rejects_non_http_in_tiles_and_legend(valves):
    _, _, r1 = norm({"layers": [{"type": "xyz", "tiles": ["javascript:1"]}]}, valves)
    _, _, r2 = norm({"layers": [{"type": "wms", "url": "https://e.com/wms", "legendUrl": "javascript:1"}]}, valves)
    assert r1 and r2


def test_relative_url_accepted(valves):
    spec, _, rejected = norm({"layers": [{"type": "geojson", "url": "/static/x.geojson"}]}, valves)
    assert not rejected and len(spec["layers"]) == 1


def test_basemap_case_insensitive(valves):
    spec, warnings, _ = norm({"basemap": "esri.worldimagery"}, valves)
    assert spec["basemap"] == "Esri.WorldImagery"
    # retired CARTO names (watermarked without a key) map to OpenFreeMap equivalents
    spec, warnings, _ = norm({"basemap": "CartoDB.DarkMatter"}, valves)
    assert spec["basemap"] == "OpenFreeMap.Dark" and not warnings
    assert not warnings


def test_basemap_default_from_valves(valves):
    spec, _, _ = norm({}, valves)
    assert spec["basemap"] == "OpenStreetMap"


def test_unknown_basemap_falls_back(valves):
    spec, warnings, _ = norm({"basemap": "Nonexistent"}, valves)
    assert spec["basemap"] == "OpenStreetMap"
    assert any("Unknown basemap" in w for w in warnings)


@pytest.mark.parametrize("custom", ["https://e.com/{z}/{x}/{y}.png", "/static/style.json"])
def test_custom_basemap_urls_kept(valves, custom):
    spec, warnings, _ = norm({"basemap": custom}, valves)
    assert spec["basemap"] == custom and not warnings


def test_center_swap_lat_lon(valves):
    spec, warnings, _ = norm({"center": [52.37, 104.9]}, valves)
    assert spec["center"] == [104.9, 52.37]
    assert any("swapped" in w for w in warnings)


def test_center_not_swapped_when_ambiguous(valves):
    spec, warnings, _ = norm({"center": [4.9, 52.37]}, valves)
    assert spec["center"] == [4.9, 52.37] and not warnings
    spec, _, _ = norm({"center": [50, 60]}, valves)
    assert spec["center"] == [50, 60]


def test_center_as_string_and_bad(valves):
    spec, _, _ = norm({"center": "4.9, 52.37"}, valves)
    assert spec["center"] == [4.9, 52.37]
    spec, _, _ = norm({"center": [1, 2, 3]}, valves)
    assert "center" not in spec
    spec, _, _ = norm({"center": ["a", "b"]}, valves)
    assert "center" not in spec


def test_bounds(valves):
    spec, _, _ = norm({"bounds": [1, 2, 3, 4]}, valves)
    assert spec["bounds"] == [1.0, 2.0, 3.0, 4.0]
    spec, _, _ = norm({"bounds": [1, 2]}, valves)
    assert "bounds" not in spec


def test_layer_bounds_invalid_removed(valves):
    spec, _, _ = norm({"layers": [{"type": "xyz", "url": "https://e.com/{z}.png", "bounds": [1, 2]}]}, valves)
    assert "bounds" not in spec["layers"][0]


@pytest.mark.parametrize("given,expected", [(10, 240), (239, 240), (240, 240), (800, 800), (5000, 1200), ("700", 700)])
def test_height_clamped(valves, given, expected):
    spec, _, _ = norm({"height": given}, valves)
    assert spec["height"] == expected


def test_height_default_and_garbage(valves):
    assert norm({}, valves)[0]["height"] == 520
    assert norm({"height": "tall"}, valves)[0]["height"] == 520


def test_numeric_coercion(valves):
    spec, warnings, _ = norm({"zoom": "7", "pitch": "x", "bearing": 12}, valves)
    assert spec["zoom"] == 7.0 and spec["bearing"] == 12.0
    assert "pitch" not in spec
    assert any(w.startswith("pitch must be a number") for w in warnings)


def test_zoom_zero_kept(valves):
    assert norm({"zoom": 0}, valves)[0]["zoom"] == 0.0


def test_passthrough_flags_and_title(valves):
    spec, _, _ = norm({"globe": True, "terrain": False, "title": ""}, valves)
    assert spec["globe"] is True and spec["terrain"] is False
    assert spec["title"] == "Map"


# ---------------------------------------------------------------------------
# 2. allowlist policy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,patterns,expected",
    [
        ("https://example.com/x", ["example.com"], True),
        ("https://EXAMPLE.com/x", ["example.com"], True),
        ("https://sub.example.com/x", ["example.com"], False),
        ("https://a.example.com/x", ["*.example.com"], True),
        ("https://a.b.example.com/x", ["*.example.com"], True),
        ("https://example.com/x", ["*.example.com"], True),
        ("https://badexample.com/x", ["*.example.com"], False),
        ("https://example.com.evil.net/x", ["*.example.com"], False),
        ("https://anything.net/x", ["*"], True),
        ("/relative/path", [], True),
        ("relative.png", [], True),
        ("https://example.com:8443/x", ["example.com:8443"], True),
        ("https://evil.net/x", ["example.com"], False),
        ("https://evil.net/x", [], False),
    ],
)
def test_host_allowed(url, patterns, expected):
    assert tool._host_allowed(url, patterns) is expected


def test_host_patterns_parsing():
    assert tool._host_patterns("https://A.com/path, b.com  *.c.org\n*") == ["a.com", "b.com", "*.c.org", "*"]
    assert tool._host_patterns("") == []


def test_allowlist_rejects_disallowed_layer_host(allow_valves):
    layers = [
        {"type": "xyz", "name": "ok", "url": "https://example.com/{z}/{x}/{y}.png"},
        {"type": "xyz", "name": "bad", "url": "https://evil.net/{z}/{x}/{y}.png"},
        {"type": "wms", "name": "wild", "url": "https://x.wild.org/wms", "layers": "a"},
        {"type": "geojson", "name": "rel", "url": "/static/a.geojson"},
        {"type": "geojson", "name": "inline", "data": {"type": "FeatureCollection", "features": []}},
    ]
    spec, _, rejected = norm({"layers": layers}, allow_valves)
    assert [l["name"] for l in spec["layers"]] == ["ok", "wild", "rel", "inline"]
    assert len(rejected) == 1 and "evil.net" in rejected[0] and "allowlist" in rejected[0]


def test_allowlist_checks_tiles_and_legend(allow_valves):
    _, _, r1 = norm({"layers": [{"type": "vectortiles", "tiles": ["https://evil.net/{z}/{x}/{y}.pbf"]}]}, allow_valves)
    _, _, r2 = norm({"layers": [{"type": "wms", "url": "https://example.com/wms", "legendUrl": "https://evil.net/l.png"}]}, allow_valves)
    assert r1 and r2


def test_open_policy_allows_any_host(valves):
    spec, _, rejected = norm({"layers": [{"type": "xyz", "url": "https://evil.net/{z}/{x}/{y}.png"}]}, valves)
    assert len(spec["layers"]) == 1 and not rejected


def test_allowlist_cog_requires_titiler_host():
    v = Tools.Valves()
    v.network_policy = "allowlist"
    v.allowed_hosts = "example.com"
    cog = {"type": "cog", "url": "https://example.com/a.tif"}
    spec, _, rejected = norm({"layers": [cog]}, v)
    assert spec["layers"] == [] and "titiler.xyz" in rejected[0]
    v.allowed_hosts = "example.com, titiler.xyz"
    spec, _, rejected = norm({"layers": [cog]}, v)
    assert len(spec["layers"]) == 1 and not rejected


def test_allowlist_cog_with_custom_titiler_layer_field():
    v = Tools.Valves()
    v.network_policy = "allowlist"
    v.allowed_hosts = "example.com, tt.example.com"
    cog = {"type": "cog", "url": "https://example.com/a.tif", "titiler": "https://tt.example.com"}
    spec, _, rejected = norm({"layers": [cog]}, v)
    assert len(spec["layers"]) == 1 and not rejected


def test_allowlist_buildings_requires_openfreemap():
    v = Tools.Valves()
    v.network_policy = "allowlist"
    v.allowed_hosts = "example.com"
    _, _, rejected = norm({"layers": [{"type": "buildings"}]}, v)
    assert rejected and "tiles.openfreemap.org" in rejected[0]
    v.allowed_hosts = "tiles.openfreemap.org"
    spec, _, rejected = norm({"layers": [{"type": "buildings"}]}, v)
    assert len(spec["layers"]) == 1


def test_allowlist_basemap_not_allowed_falls_back_to_none():
    v = Tools.Valves()
    v.network_policy = "allowlist"
    v.allowed_hosts = "example.com"
    spec, warnings, _ = norm({"basemap": "OpenStreetMap"}, v)
    assert spec["basemap"] == "None"
    assert any("not on the admin allowlist" in w for w in warnings)


def test_allowlist_basemap_allowed_kept(allow_valves):
    spec, warnings, _ = norm({"basemap": "OpenStreetMap"}, allow_valves)
    assert spec["basemap"] == "OpenStreetMap" and not warnings


def test_allowlist_basemap_needs_all_subdomains():
    v = Tools.Valves()
    v.network_policy = "allowlist"
    v.allowed_hosts = "a.tile.opentopomap.org"
    spec, _, _ = norm({"basemap": "OpenTopoMap"}, v)
    assert spec["basemap"] == "None"
    v.allowed_hosts = "*.tile.opentopomap.org"
    spec, _, _ = norm({"basemap": "OpenTopoMap"}, v)
    assert spec["basemap"] == "OpenTopoMap"


def test_allowlist_vector_style_basemap_checked():
    v = Tools.Valves()
    v.network_policy = "allowlist"
    v.allowed_hosts = "example.com"
    assert norm({"basemap": "OpenFreeMap.Liberty"}, v)[0]["basemap"] == "None"
    v.allowed_hosts = "tiles.openfreemap.org"
    assert norm({"basemap": "OpenFreeMap.Liberty"}, v)[0]["basemap"] == "OpenFreeMap.Liberty"


def test_allowlist_custom_basemap_url_blocked(allow_valves):
    spec, _, _ = norm({"basemap": "https://evil.net/{z}/{x}/{y}.png"}, allow_valves)
    assert spec["basemap"] == "None"


def test_allowlist_none_basemap_is_fine(allow_valves):
    spec, warnings, _ = norm({"basemap": "none"}, allow_valves)
    assert spec["basemap"] == "None" and not warnings


def test_default_allowlist_covers_default_basemap_and_cdn():
    v = Tools.Valves()
    v.network_policy = "allowlist"
    spec, warnings, _ = norm({}, v)
    assert spec["basemap"] == "OpenStreetMap" and not warnings
    pats = tool._host_patterns(v.allowed_hosts)
    assert tool._host_allowed(v.maplibre_js_url, pats)
    assert tool._host_allowed(v.pmtiles_js_url, pats)
    assert tool._host_allowed(v.titiler_endpoint, pats)


# ---------------------------------------------------------------------------
# 3. CSP
# ---------------------------------------------------------------------------


def test_csp_open(valves):
    csp = tool._csp_tag(valves)
    assert csp.startswith('<meta http-equiv="Content-Security-Policy"')
    assert "worker-src blob:" in csp
    assert "object-src 'none'" in csp
    assert "script-src" not in csp  # open policy does not restrict fetch directives


def test_csp_allowlist_includes_required_hosts():
    v = Tools.Valves()
    v.network_policy = "allowlist"
    v.allowed_hosts = "example.com, *.wild.org"
    v.maplibre_js_url = "https://cdn.one.net/maplibre.js"
    v.maplibre_css_url = "https://cdn.two.net/maplibre.css"
    v.pmtiles_js_url = "https://cdn.three.net/pmtiles.js"
    v.titiler_endpoint = "https://titiler.four.net"
    csp = tool._csp_tag(v)
    for host in ("https://example.com", "https://*.wild.org", "https://cdn.one.net", "https://cdn.two.net",
                 "https://cdn.three.net", "https://titiler.four.net"):
        assert host in csp
    assert "worker-src blob:" in csp
    assert "default-src 'self'" in csp
    assert "object-src 'none'" in csp
    assert "https://evil.net" not in csp


def test_csp_allowlist_defaults_include_cdn_and_titiler():
    v = Tools.Valves()
    v.network_policy = "allowlist"
    csp = tool._csp_tag(v)
    assert "https://unpkg.com" in csp and "https://titiler.xyz" in csp


def test_csp_allowlist_no_bare_star_by_default():
    v = Tools.Valves()
    v.network_policy = "allowlist"
    tokens = tool._csp_tag(v).replace(";", " ").split()
    assert "*" not in tokens


def test_csp_allowlist_star_when_configured():
    v = Tools.Valves()
    v.network_policy = "allowlist"
    v.allowed_hosts = "*"
    assert "*" in tool._csp_tag(v).replace(";", " ").split()


def test_csp_relative_self_hosted_urls_ignored():
    v = Tools.Valves()
    v.network_policy = "allowlist"
    v.allowed_hosts = "example.com"
    v.maplibre_js_url = "/static/maplibre.js"
    csp = tool._csp_tag(v)
    assert "https:///" not in csp and "://;" not in csp


# ---------------------------------------------------------------------------
# 4. _build_html
# ---------------------------------------------------------------------------

XSS = "</script><script>alert(1)</script>"


def geojson_layer(prop=XSS):
    return {"type": "geojson", "name": "pts", "data": {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {"name": prop},
                      "geometry": {"type": "Point", "coordinates": [0, 0]}}]}}


def build(raw, v=None):
    v = v or Tools.Valves()
    spec, _, _ = tool._normalise_spec(raw, v)
    return tool._build_html(spec, v)


def test_config_json_escapes_script_close():
    html = build({"layers": [geojson_layer()]})
    assert XSS not in html
    assert "</script><script>alert(1)" not in html
    assert "alert(1)" in html  # present, but only inside the escaped JSON
    assert "\\u003c/script\\u003e" in html


def test_config_roundtrips():
    html = build({"title": "T", "layers": [geojson_layer()]})
    start = html.index('id="mv-config">') + len('id="mv-config">')
    cfg = json.loads(html[start:html.index("</script>", start)])
    assert cfg["spec"]["layers"][0]["data"]["features"][0]["properties"]["name"] == XSS
    assert cfg["maplibreJs"].endswith("maplibre-gl.js")


def test_json_for_html_escapes():
    out = tool._json_for_html({"a": "<>&\u2028\u2029"})
    for ch in ("<", ">", "&", "\u2028", "\u2029"):
        assert ch not in out
    assert json.loads(out) == {"a": "<>&\u2028\u2029"}


def test_json_for_html_keeps_plain_spaces():
    assert json.loads(tool._json_for_html({"a": "hello world"})) == {"a": "hello world"}


def test_only_expected_script_tags():
    html = build({"layers": [geojson_layer()]})
    # maplibre, config, main script
    assert html.count("<script") == 3
    assert html.count("</script>") == 3


def test_pmtiles_script_only_with_pmtiles_layer():
    v = Tools.Valves()
    without = build({"layers": [geojson_layer("x")]}, v)
    assert v.pmtiles_js_url not in without
    with_pm = build({"layers": [{"type": "pmtiles", "url": "https://e.com/a.pmtiles"}]}, v)
    # loaded asynchronously by BOOT_SCRIPT from the config, never via a blocking <script src>
    assert '"pmtilesJs":"%s"' % v.pmtiles_js_url in with_pm
    assert "<script src=" not in with_pm


def test_title_html_escaped():
    html = build({"title": '<img src=x onerror=alert(1)> & "q"'})
    assert "<img src=x" not in html
    assert "<title>&lt;img src=x onerror=alert(1)&gt; &amp; &quot;q&quot;</title>" in html


def test_urls_attribute_escaped():
    v = Tools.Valves()
    v.maplibre_js_url = 'https://e.com/a.js"><script>alert(1)</script>'
    html = build({}, v)
    assert 'a.js"><script>' not in html


def test_html_structure_and_csp_present():
    html = build({})
    assert html.startswith("<!DOCTYPE html>")
    assert "Content-Security-Policy" in html
    assert 'id="mv-wrap"' in html


# ---------------------------------------------------------------------------
# 5. show_map
# ---------------------------------------------------------------------------


LAYERS = [
    {"type": "xyz", "name": "Bottom", "url": "https://e.com/{z}/{x}/{y}.png"},
    {"type": "geojson", "name": "Top", "visible": False, "data": {"type": "FeatureCollection", "features": []}},
    {"type": "wms", "name": "Broken"},
    {"type": "xyz", "name": "Js", "url": "javascript:alert(1)"},
]


def test_show_map_with_emitter():
    events = []

    async def emitter(ev):
        events.append(ev)

    result = run(Tools().show_map(title="My <Map>", layers=LAYERS, basemap="bogus", __event_emitter__=emitter))
    assert isinstance(result, str)
    # the embed, then a status line for the chat
    assert [e["type"] for e in events] == ["embeds", "status"]
    assert events[1]["data"] == {"description": "Map: 2 layers, 2 rejected", "done": True}
    ev = events[0]
    assert ev["type"] == "embeds"
    assert list(ev["data"].keys()) == ["embeds"] and len(ev["data"]["embeds"]) == 1
    html = ev["data"]["embeds"][0]
    assert html.startswith("<!DOCTYPE html>") and "My &lt;Map&gt;" in html

    assert result.index("1. Bottom [xyz, visible]") < result.index("2. Top [geojson, hidden]")
    assert "Layers, bottom to top:" in result
    assert "Rejected layers" in result
    assert "layers[2] (Broken)" in result and "layers[3] (Js)" in result
    assert "Unknown basemap 'bogus'" in result


def test_show_map_without_emitter_returns_response_and_summary():
    from fastapi.responses import HTMLResponse

    out = run(Tools().show_map(layers=LAYERS[:1]))
    assert isinstance(out, tuple) and len(out) == 2
    resp, summary = out
    assert isinstance(resp, HTMLResponse)
    assert resp.headers["content-disposition"] == "inline"
    assert b"mv-config" in resp.body
    assert "1. Bottom [xyz, visible]" in summary


def test_show_map_no_layers_summary():
    out = run(Tools().show_map())
    assert "No overlay layers." in out[1]


def test_show_map_respects_valves():
    t = Tools()
    t.valves.network_policy = "allowlist"
    t.valves.allowed_hosts = "example.com"
    summary = run(t.show_map(layers=[{"type": "xyz", "url": "https://evil.net/{z}.png"}]))[1]
    assert "allowlist" in summary and "basemap: None" in summary


# ---------------------------------------------------------------------------
# 6. Capabilities parsing via inspect_ogc_service
# ---------------------------------------------------------------------------


@pytest.fixture
def http(monkeypatch):
    """Route tool._http_get to a dict of {url-substring: bytes|Exception}; records calls."""
    calls = []
    routes = {}

    def fake(url, allow_private, timeout, max_bytes=8_000_000):
        calls.append(url)
        for key, val in routes.items():
            if key in url:
                if isinstance(val, Exception):
                    raise val
                return val
        raise OSError("no route for " + url)

    monkeypatch.setattr(tool, "_http_get", fake)
    fake.calls = calls
    fake.routes = routes
    return fake


def inspect(**kw):
    return json.loads(run(Tools().inspect_ogc_service(**kw)))


def test_wms_130(http):
    http.routes["SERVICE=WMS"] = fixture_bytes("wms130.xml")
    out = inspect(url="https://e.com/wms", service="wms")
    assert out["service"] == "WMS" and out["version"] == "1.3.0" and out["title"] == "Test WMS"
    assert out["getmap_formats"] == ["image/png", "image/jpeg"]
    assert out["featureinfo_formats"] == ["application/json", "text/html"]
    assert out["endpoint"] == "https://e.com/wms"
    by_name = {l["name"]: l for l in out["layers"]}
    assert set(by_name) == {"roads", "rivers", "no3857"}
    roads = by_name["roads"]
    assert roads["epsg3857"] is True and roads["queryable"] is True
    assert roads["styles"] == ["default", "dark"]
    assert roads["bounds"] == [3.12346, 50.5, 7.2, 53.7]
    assert roads["abstract"] == "All the roads"
    assert by_name["rivers"]["epsg3857"] is True  # inherited through nested group
    assert by_name["rivers"]["queryable"] is False
    assert by_name["no3857"]["epsg3857"] is False
    assert out["layer_count"] == 3


def test_wms_111(http):
    http.routes["SERVICE=WMS"] = fixture_bytes("wms111.xml")
    out = inspect(url="https://e.com/wms", service="wms")
    assert out["version"] == "1.1.1" and out["title"] == "Old WMS"
    (layer,) = out["layers"]
    assert layer["name"] == "landuse" and layer["epsg3857"] is True  # 900913 alias via SRS
    assert layer["bounds"] == [-10.0, 35.0, 30.0, 60.0]
    assert layer["queryable"] is False


def test_wfs_200(http):
    http.routes["SERVICE=WFS"] = fixture_bytes("wfs200.xml")
    out = inspect(url="https://e.com/wfs", service="wfs")
    assert out["service"] == "WFS" and out["title"] == "Test WFS"
    assert "application/json" in out["output_formats"]
    assert out["json_output"] is True
    names = {l["name"]: l for l in out["layers"]}
    assert set(names) == {"ns:buildings", "ns:lakes"}
    b = names["ns:buildings"]
    assert b["bounds"] == [3.3, 50.7, 7.2, 53.6]
    assert b["default_crs"] == "urn:ogc:def:crs:EPSG::28992"
    assert names["ns:lakes"]["bounds"] is None


def test_wfs_without_json(http):
    http.routes["SERVICE=WFS"] = fixture_bytes("wfs200.xml").replace(b"application/json", b"text/xml")
    assert inspect(url="https://e.com/wfs", service="wfs")["json_output"] is False


def test_wmts_100(http):
    http.routes["SERVICE=WMTS"] = fixture_bytes("wmts100.xml")
    out = inspect(url="https://e.com/wmts", service="wmts")
    layers = {l["name"]: l for l in out["layers"]}
    aerial = layers["aerial"]
    assert aerial["formats"] == ["image/jpeg"] and aerial["styles"] == ["default"]
    assert aerial["rest_template"].startswith("https://t.example.com/aerial/")
    assert aerial["web_mercator_sets"] == [
        {"tileMatrixSet": "GoogleMapsCompatible", "first_matrix_id": "0", "usable": True, "matrixPrefix": ""}]

    pref = layers["prefixed"]["web_mercator_sets"]
    assert pref == [{"tileMatrixSet": "EPSG:3857", "first_matrix_id": "EPSG:3857:0", "usable": True,
                     "matrixPrefix": "EPSG:3857:"}]  # EPSG:28992 set is not Web Mercator
    assert layers["prefixed"]["rest_template"] is None

    padded = layers["padded"]["web_mercator_sets"][0]
    assert padded["first_matrix_id"] == "00" and padded["usable"] is False and padded["matrixPrefix"] is None
    assert "note" in out


def test_ogc_exception_report(http):
    http.routes["SERVICE=WMS"] = fixture_bytes("ows_exception.xml")
    out = inspect(url="https://e.com/wms", service="wms")
    assert out["error"] == "Could not read capabilities"
    assert "Unknown service" in out["attempts"][0] and out["attempts"][0].startswith("WMS:")


def test_wrong_root_element(http):
    http.routes["SERVICE=WMS"] = fixture_bytes("wfs200.xml")
    out = inspect(url="https://e.com/ows", service="wms")
    assert "unexpected root" in out["attempts"][0]


def test_non_xml_response(http):
    http.routes["SERVICE=WMS"] = b"<html><body>no"
    out = inspect(url="https://e.com/ows", service="wms")
    assert "not XML" in out["attempts"][0]


def test_http_error_reported(http):
    http.routes["SERVICE=WMS"] = urllib.error.HTTPError("u", 404, "Not Found", {}, None)
    out = inspect(url="https://e.com/ows", service="wms")
    assert "HTTP 404 Not Found" in out["attempts"][0]


def test_ogcapi_collections(http):
    http.routes["/collections?f=json"] = fixture_bytes("collections.json")
    out = inspect(url="https://e.com/api/collections/lakes/items?x=1", service="ogcapi")
    assert http.calls == ["https://e.com/api/collections?f=json"]
    assert out["service"] == "OGC API Features" and out["api_root"] == "https://e.com/api"
    by = {l["name"]: l for l in out["layers"]}
    assert by["lakes"]["bounds"] == [3.0, 50.0, 7.0, 54.0]
    assert by["rivers"]["bounds"] is None
    assert by["roads"]["abstract"] == "Streets"


def test_ogcapi_not_json(http):
    http.routes["/collections?f=json"] = b"<html/>"
    out = inspect(url="https://e.com/api", service="ogcapi")
    assert "not JSON" in out["attempts"][0]


def test_search_filters(http):
    http.routes["SERVICE=WMS"] = fixture_bytes("wms130.xml")
    out = inspect(url="https://e.com/wms", service="wms", search="ROAD")
    assert [l["name"] for l in out["layers"]] == ["roads"]
    assert out["layer_count"] == 1 and "truncated" not in out
    out = inspect(url="https://e.com/wms", service="wms", search="all the")  # matches abstract
    assert [l["name"] for l in out["layers"]] == ["roads"]


def test_limit_truncates(http):
    http.routes["SERVICE=WMS"] = fixture_bytes("wms130.xml")
    out = inspect(url="https://e.com/wms", service="wms", limit=2)
    assert len(out["layers"]) == 2 and out["layer_count"] == 3
    assert "Showing 2 of 3" in out["truncated"]


def test_limit_clamped(http):
    http.routes["SERVICE=WMS"] = fixture_bytes("wms130.xml")
    assert len(inspect(url="https://e.com/wms", service="wms", limit=-5)["layers"]) == 1
    assert len(inspect(url="https://e.com/wms", service="wms", limit=100000)["layers"]) == 3


def test_caps_url_construction():
    u = tool._caps_url("https://e.com/ows?map=x.map&SERVICE=old&Request=GetMap&version=9", "wfs")
    assert "map=x.map" in u
    assert u.count("SERVICE=") == 1 and "SERVICE=WFS" in u and "REQUEST=GetCapabilities" in u and "VERSION=2.0.0" in u
    assert "old" not in u and "version=9" not in u


@pytest.mark.parametrize(
    "url,order",
    [
        ("https://e.com/ows?service=WFS", ["WFS"]),
        ("https://e.com/geoserver/wfs", ["WFS", "WMS", "WMTS"]),
        ("https://e.com/wmts", ["WMTS", "WMS", "WFS"]),
        ("https://e.com/api/collections", ["OGCAPI", "WMS", "WFS"]),
        ("https://e.com/plain", ["WMS", "WFS", "WMTS", "OGCAPI"]),
    ],
)
def test_auto_order(http, url, order):
    out = inspect(url=url, service="auto")
    assert out["error"] == "Could not read capabilities"
    got = [a.split(":")[0] for a in out["attempts"]]
    assert got == order


def test_auto_falls_through_to_working_service(http):
    http.routes["SERVICE=WFS"] = fixture_bytes("wfs200.xml")
    http.routes["SERVICE=WMS"] = fixture_bytes("ows_exception.xml")
    out = inspect(url="https://e.com/plain", service="auto")
    assert out["service"] == "WFS"
    assert [c for c in http.calls if "SERVICE=WMS" in c]  # WMS tried first


def test_auto_ogcapi_ordering_calls(http):
    http.routes["/collections?f=json"] = fixture_bytes("collections.json")
    out = inspect(url="https://e.com/api/collections")
    assert out["service"] == "OGC API Features" and len(http.calls) == 1


def test_inspect_allowlist_blocks_host(http):
    t = Tools()
    t.valves.network_policy = "allowlist"
    t.valves.allowed_hosts = "example.com"
    out = json.loads(run(t.inspect_ogc_service(url="https://evil.net/wms")))
    assert "not on the admin allowlist" in out["error"]
    assert http.calls == []


# ---------------------------------------------------------------------------
# 7. SSRF guard
# ---------------------------------------------------------------------------


def fake_dns(monkeypatch, *ips):
    def gai(host, port, *a, **k):
        return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in ips]

    monkeypatch.setattr(socket, "getaddrinfo", gai)


@pytest.mark.parametrize(
    "ip",
    ["127.0.0.1", "10.0.0.5", "192.168.1.1", "172.16.5.5", "169.254.169.254", "0.0.0.0", "100.64.0.1",
     "::1", "fe80::1", "fc00::1", "::ffff:127.0.0.1"],
)
def test_check_public_rejects_non_public(monkeypatch, ip):
    fake_dns(monkeypatch, ip)
    with pytest.raises(ValueError, match="non-public"):
        tool._check_public("http://some.host/x", False)


def test_check_public_rejects_if_any_result_private(monkeypatch):
    fake_dns(monkeypatch, "8.8.8.8", "10.0.0.1")
    with pytest.raises(ValueError, match="non-public"):
        tool._check_public("https://dual.host/", False)


def test_check_public_accepts_public(monkeypatch):
    fake_dns(monkeypatch, "8.8.8.8", "2606:4700:4700::1111")
    tool._check_public("https://good.host/x", False)


def test_check_public_strips_ipv6_scope(monkeypatch):
    fake_dns(monkeypatch, "fe80::1%eth0")
    with pytest.raises(ValueError, match="non-public"):
        tool._check_public("http://h/", False)


@pytest.mark.parametrize("url", ["ftp://e.com/x", "file:///etc/passwd", "javascript:alert(1)", "/relative", "http://", ""])
def test_check_public_rejects_bad_schemes(url):
    with pytest.raises(ValueError, match="Only absolute"):
        tool._check_public(url, True)  # even with allow_private


def test_check_public_allow_private_bypasses_dns(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("DNS must not be consulted")

    monkeypatch.setattr(socket, "getaddrinfo", boom)
    tool._check_public("http://10.0.0.1/x", True)


def test_check_public_dns_failure(monkeypatch):
    def gai(*a, **k):
        raise socket.gaierror(-2, "Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", gai)
    with pytest.raises(ValueError, match="Cannot resolve"):
        tool._check_public("http://nope.invalid/", False)


def test_inspect_private_host_returns_json_error(monkeypatch):
    fake_dns(monkeypatch, "192.168.0.10")

    def no_open(*a, **k):
        raise AssertionError("must not open a connection")

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", no_open)
    out = json.loads(run(Tools().inspect_ogc_service(url="http://intranet.local/wms", service="auto")))
    assert "non-public" in out["error"] and "attempts" not in out


def test_inspect_unresolvable_host_returns_json_error(monkeypatch):
    def gai(*a, **k):
        raise socket.gaierror(-2, "nx")

    monkeypatch.setattr(socket, "getaddrinfo", gai)
    out = json.loads(run(Tools().inspect_ogc_service(url="http://nope.invalid/wms", service="wms")))
    assert "Cannot resolve" in out["error"]


def test_inspect_bad_scheme_returns_json_error():
    out = json.loads(run(Tools().inspect_ogc_service(url="file:///etc/passwd", service="wms")))
    assert "Only absolute" in out["error"]


def test_inspect_allow_private_valve_passed_through(monkeypatch):
    seen = {}

    def fake(url, allow_private, timeout, max_bytes=8_000_000):
        seen["allow"], seen["timeout"] = allow_private, timeout
        return fixture_bytes("wms130.xml")

    monkeypatch.setattr(tool, "_http_get", fake)
    t = Tools()
    t.valves.allow_private_networks = True
    t.valves.request_timeout = 7
    out = json.loads(run(t.inspect_ogc_service(url="http://10.1.1.1/wms", service="wms")))
    assert out["service"] == "WMS" and seen == {"allow": True, "timeout": 7}


def test_http_get_checks_before_opening(monkeypatch):
    fake_dns(monkeypatch, "127.0.0.1")
    with pytest.raises(ValueError, match="non-public"):
        tool._http_get("http://localhost/x", False, 5)


def test_redirect_handler_rechecks(monkeypatch):
    fake_dns(monkeypatch, "169.254.169.254")
    handler = tool._GuardedRedirect(False)
    req = urllib.request.Request("https://public.example/x")
    with pytest.raises(ValueError, match="non-public"):
        handler.redirect_request(req, None, 302, "Found", {}, "http://metadata.internal/latest")


def test_redirect_handler_rejects_scheme_downgrade_to_file():
    handler = tool._GuardedRedirect(True)
    req = urllib.request.Request("https://public.example/x")
    with pytest.raises(ValueError, match="Only absolute"):
        handler.redirect_request(req, None, 302, "Found", {}, "file:///etc/passwd")


def test_redirect_handler_allows_public(monkeypatch):
    fake_dns(monkeypatch, "8.8.8.8")
    handler = tool._GuardedRedirect(False)
    req = urllib.request.Request("https://public.example/x")
    new = handler.redirect_request(req, None, 302, "Found", {"location": "https://other.example/y"}, "https://other.example/y")
    assert new is not None and new.full_url == "https://other.example/y"


def test_http_get_installs_guarded_redirect_and_size_cap(monkeypatch):
    fake_dns(monkeypatch, "8.8.8.8")
    captured = {}

    class FakeResp:
        def __init__(self, n):
            self.n = n

        def read(self, n):
            return b"x" * min(self.n, n)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class FakeOpener:
        def open(self, req, timeout=None):
            captured["req"], captured["timeout"] = req, timeout
            return FakeResp(captured["size"])

    def build_opener(*handlers):
        captured["handlers"] = handlers
        return FakeOpener()

    monkeypatch.setattr(urllib.request, "build_opener", build_opener)
    captured["size"] = 10
    assert tool._http_get("https://public.example/c", False, 3) == b"x" * 10
    assert any(isinstance(h, tool._GuardedRedirect) and h.allow_private is False for h in captured["handlers"])
    assert captured["timeout"] == 3
    assert captured["req"].get_header("User-agent").startswith("OpenWebUI-MapVisualizer/")
    captured["size"] = 100
    with pytest.raises(ValueError, match="larger than 8 MB"):
        tool._http_get("https://public.example/c", False, 3, max_bytes=50)


# ---------------------------------------------------------------------------
# 8. Module-level srcdoc safety
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("token", tool._FORBIDDEN_SRCDOC_TOKENS)
def test_no_forbidden_tokens_in_script_or_css(token):
    assert token not in tool.MAP_SCRIPT
    assert token not in tool.MAP_CSS


def test_forbidden_token_list_complete():
    for t in ("<!--", "-->", "<script", "</script"):
        assert t in tool._FORBIDDEN_SRCDOC_TOKENS


def test_built_page_script_not_truncated():
    html = build({})
    # config JSON, then the mvMain definition, then the boot script
    assert html.count("<script") == 3 and html.count("</script>") == 3
    assert html.endswith("</script></body></html>")
    main = html.split("<script>window.mvMain = function () {", 1)[1].split("</script>", 1)[0]
    assert main.rstrip().endswith("};") and "})();" in main
    assert "<!--" not in html and "-->" not in html
