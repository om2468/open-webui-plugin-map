"""Map store, update_map, describe_map and look_at_map (0.3.0)."""
import asyncio
import json

import tool
from tool import Tools


def run(coro):
    return asyncio.run(coro)


def mem_tools():
    t = Tools()
    t.store = tool._MapStore(None)  # memory only
    return t


def collect():
    events = []

    async def emitter(ev):
        events.append(ev)

    return events, emitter


CHAT = {"chat_id": "chat-A"}
GJ = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"n": 1}, "geometry": {"type": "Point", "coordinates": [5, 52]}}]}


def test_map_id_normalisation():
    assert tool._map_id("m2") == "m2" and tool._map_id("M2") == "m2" and tool._map_id("map 2") == "m2"
    assert tool._map_id(3) == "m3" and tool._map_id("3") == "m3"
    assert tool._map_id(None) is None and tool._map_id("latest") is None and tool._map_id("") is None


def test_map_store_persists_and_limits(tmp_path):
    store = tool._MapStore(str(tmp_path))
    a = store.create("chat/1", {"title": "A", "layers": []})
    b = store.create("chat/1", {"title": "B", "layers": []})
    assert (a["id"], b["id"]) == ("m1", "m2")
    assert store.get("chat/1")["id"] == "m2" and store.get("chat/1", "m1")["id"] == "m1"
    assert store.get("chat/1", "m9") is None and store.get("other") is None
    store.bump("chat/1", a)
    assert a["version"] == 2
    # a fresh store reads the file back (the chat id is sanitised into the file name)
    again = tool._MapStore(str(tmp_path))
    assert again.get("chat/1", "m1")["version"] == 2 and again.get("chat/1")["id"] == "m2"
    assert (tmp_path / "chat_1.json").exists()
    for i in range(tool._MAPS_PER_CHAT + 3):
        store.create("chat/1", {"title": str(i), "layers": []})
    data = store._load("chat/1")
    assert len(data["order"]) == tool._MAPS_PER_CHAT and "m1" not in data["maps"]
    assert data["order"][-1] == f"m{tool._MAPS_PER_CHAT + 5}"  # ids never reused
    # a file from 0.3.0-dev without "next" still continues the sequence
    data.pop("next")
    assert store.create("chat/1", {"title": "n", "layers": []})["id"] == f"m{tool._MAPS_PER_CHAT + 6}"
    # no chat id: nothing written
    tool._MapStore(str(tmp_path)).create("", {"title": "x", "layers": []})
    assert sorted(p.name for p in tmp_path.iterdir()) == ["chat_1.json"]


def test_find_layer():
    layers = [{"name": "Rivers"}, {"name": "Big Cities"}, {"name": "3"}]
    f = tool._find_layer
    assert f(layers, "rivers") == 0 and f(layers, "Big Cities") == 1
    assert f(layers, 2) == 1 and f(layers, "2") == 1 and f(layers, 3.0) == 2
    assert f(layers, {"name": "Rivers"}) == 0 and f(layers, {"index": 1, "name": "ignored"}) == 0
    assert f(layers, "cities") == 1  # partial match
    assert f(layers, "nothing") is None and f(layers, 0) is None and f(layers, 4) is None
    assert f(layers, True) is None and f(layers, None) is None


def test_patch_layers():
    layers = [{"name": "A", "type": "xyz", "style": {"color": "#111", "label": "n"}}, {"name": "B", "type": "wms"}, {"name": "C", "type": "geojson"}]
    errors = []
    out = tool._patch_layers(layers, [
        {"name": "A", "visible": False, "opacity": 0.4, "style": {"color": "#222", "label": None, "width": 3}},
        {"index": 2, "rename": "B2", "layers": "x,y"},
        {"name": "C", "position": 1},
        {"name": "missing", "visible": True},
        "junk",
    ], ["b2", "nope"], [{"name": "D", "type": "xyz", "url": "https://e.com/{z}/{x}/{y}.png"}], errors)
    assert [l["name"] for l in out] == ["C", "A", "D"]
    a = out[1]
    assert a["visible"] is False and a["opacity"] == 0.4 and a["style"] == {"color": "#222", "width": 3}
    assert layers[0]["style"] == {"color": "#111", "label": "n"}  # input untouched
    assert len(errors) == 3 and "missing" in errors[0] and "not an object" in errors[1] and "nope" in errors[2]


def test_show_map_registers_maps_per_chat():
    t = mem_tools()
    events, emitter = collect()
    r1 = run(t.show_map(title="One", layers=[{"type": "geojson", "name": "Pts", "data": GJ}], __event_emitter__=emitter, __metadata__=CHAT))
    r2 = run(t.show_map(title="Two", __event_emitter__=emitter, __metadata__=CHAT))
    r3 = run(t.show_map(title="Other chat", __event_emitter__=emitter, __metadata__={"chat_id": "chat-B"}))
    assert r1.startswith("Map m1 ") and r2.startswith("Map m2 ") and r3.startswith("Map m1 ")
    assert '"mapId":"m1","mapVersion":1' in events[0]["data"]["embeds"][0]
    assert "1 features inline" in r1
    assert t.store.get("chat-A")["id"] == "m2" and t.store.get("chat-B")["spec"]["title"] == "Other chat"


def test_update_map_patches_and_reemits():
    t = mem_tools()
    events, emitter = collect()
    assert run(t.update_map(__metadata__=CHAT)).startswith("There is no map in this chat yet.")
    run(t.show_map(title="T", layers=[
        {"type": "xyz", "name": "Base", "url": "https://e.com/{z}/{x}/{y}.png"},
        {"type": "geojson", "name": "Pts", "data": GJ, "style": {"color": "#111"}},
    ], bounds=[4, 51, 6, 53], __event_emitter__=emitter, __metadata__=CHAT))
    events.clear()
    out = run(t.update_map(
        update_layers=[{"name": "pts", "style": {"label": "n"}, "opacity": 0.5}, {"name": "ghost", "visible": False}],
        add_layers=[{"type": "wms", "name": "Overlay", "url": "https://e.com/wms", "layers": "a"}, {"type": "shp", "name": "Bad"}],
        center=[5.1, 52.1], zoom=9, title="T2", __event_emitter__=emitter, __metadata__=CHAT))
    assert out.startswith('Map m1 "T2" was updated (version 2)')
    assert "1. Base [xyz, visible]" in out and "2. Pts [geojson, visible, 1 features inline]" in out and "3. Overlay [wms, visible]" in out
    assert "Problems with this request:" in out and "ghost" in out
    assert "Rejected layers" in out and "Bad" in out
    rec = t.store.get("chat-A")
    assert rec["version"] == 2 and rec["spec"]["layers"][1]["style"] == {"color": "#111", "label": "n"}
    assert rec["spec"]["layers"][1]["opacity"] == 0.5
    assert rec["spec"]["center"] == [5.1, 52.1] and rec["spec"]["zoom"] == 9 and "bounds" not in rec["spec"]
    assert [e["type"] for e in events] == ["embeds", "status"]
    assert '"mapId":"m1","mapVersion":2' in events[0]["data"]["embeds"][0]
    assert events[1]["data"]["description"] == "Map m1: 3 layers, 1 rejected"
    # remove by index, bounds replaces center, explicit id, JSON strings tolerated
    out = run(t.update_map(map_id="M1", remove_layers='["1"]', bounds=[1, 2, 3, 4], __metadata__=CHAT))
    spec = t.store.get("chat-A")["spec"]
    assert [l["name"] for l in spec["layers"]] == ["Pts", "Overlay"] and spec["bounds"] == [1, 2, 3, 4] and "center" not in spec
    assert "version 3" in out
    assert run(t.update_map(map_id="m7", __metadata__=CHAT)).startswith("No map 'm7' in this chat.")
    assert run(t.update_map(__metadata__={"chat_id": "chat-B"})).startswith("There is no map")  # other chats cannot see it


def test_describe_map():
    t = mem_tools()
    assert json.loads(run(t.describe_map(__metadata__=CHAT)))["error"].startswith("No such map")
    run(t.show_map(title="D", layers=[
        {"type": "wms", "name": "W", "url": "https://e.com/wms", "layers": "l1", "opacity": 0.3},
        {"type": "geojson", "name": "G", "data": GJ, "style": {"radius": 4}, "visible": False},
    ], center=[5, 52], zoom=7, __metadata__=CHAT))
    d = json.loads(run(t.describe_map(__metadata__=CHAT)))
    assert d["map_id"] == "m1" and d["version"] == 1 and d["title"] == "D" and d["basemap"] == "OpenStreetMap"
    assert d["view"] == {"center": [5.0, 52.0], "zoom": 7.0}
    assert d["layers"][0] == {"index": 1, "name": "W", "type": "wms", "visible": True, "opacity": 0.3, "url": "https://e.com/wms", "layers": "l1"}
    assert d["layers"][1]["features"] == 1 and d["layers"][1]["visible"] is False and d["layers"][1]["style"] == {"radius": 4}
    assert "last_look" not in d
    assert "error" in json.loads(run(mem_tools().describe_map(__metadata__=CHAT)))  # another instance, own store


SNAP = {"ok": True, "version": 1, "settled": True, "title": "L", "basemap": "OpenStreetMap",
        "view": {"center": [5, 52], "zoom": 8.5, "pitch": 0, "bearing": 0, "bounds": [4, 51, 6, 53]},
        "layers": [
            {"index": 1, "name": "Good", "type": "wms", "state": "ready", "visible": True, "tilesLoaded": True, "rendered": 0},
            {"index": 2, "name": "Bad", "type": "wms", "state": "ready", "visible": True, "tilesLoaded": False, "note": "Tiles failed to load (HTTP 400)", "rendered": 0},
            {"index": 3, "name": "Pts", "type": "geojson", "state": "ready", "visible": False, "featureCount": 1, "rendered": 0, "edited": True},
            {"index": 4, "name": "Wfs", "type": "wfs", "state": "error", "error": "HTTP 400 Bad Request", "visible": True},
        ], "png": "data:image/jpeg;base64,AAAA", "pngSize": [1000, 520]}


def look_tools(valves=None):
    t = mem_tools()
    for k, v in (valves or {}).items():
        setattr(t.valves, k, v)
    run(t.show_map(title="L", __metadata__=CHAT))
    return t


def fake_call(result, delay=0.0, calls=None):
    async def call(ev):
        if calls is not None:
            calls.append(ev)
        await asyncio.sleep(delay)
        if isinstance(result, Exception):
            raise result
        return result
    return call


def test_look_at_map_reports_layer_states_without_vision():
    t = look_tools({"vision_model": "off"})
    assert run(t.look_at_map(__metadata__=CHAT)).startswith("look_at_map needs a live chat session")
    assert run(look_tools().look_at_map(__metadata__={"chat_id": "none"}, __event_call__=fake_call("{}"))).startswith("There is no map")
    calls = []
    events, emitter = collect()
    out = run(t.look_at_map(__event_call__=fake_call(json.dumps(SNAP), calls=calls), __event_emitter__=emitter, __metadata__=CHAT))
    assert calls[0]["type"] == "execute" and '"mapId":"m1",' in calls[0]["data"]["code"]
    assert '{"op": "snapshot", "png": false}' in calls[0]["data"]["code"]
    assert out.startswith('Map m1 (version 1) "L", basemap OpenStreetMap.')
    assert "View: center [5, 52], zoom 8.5" in out and "bounds [W,S,E,N] [4, 51, 6, 53]" in out
    assert "1. Good [wms] visible, loaded" in out
    assert "2. Bad [wms] visible, loaded, no tiles loaded yet, note: Tiles failed to load (HTTP 400)" in out
    assert "3. Pts [geojson] hidden, loaded, 1 features, 0 drawn in view, edited by the user" in out
    assert "4. Wfs [wfs] visible, ERROR: HTTP 400 Bad Request" in out
    assert "Problems to fix" in out and "Wfs: HTTP 400 Bad Request" in out and "Bad: Tiles failed" in out
    assert "screenshot" not in out.lower()
    assert events[-1]["data"] == {"description": "Looked at map m1: 2 problems", "done": True}
    look = t.store.get("chat-A")["look"]
    assert "png" not in json.dumps(look) and look["layers"][3]["state"] == "error"
    assert json.loads(run(t.describe_map(__metadata__=CHAT)))["last_look"]["view"]["zoom"] == 8.5


def test_look_at_map_with_vision(monkeypatch):
    t = look_tools()
    seen = {}

    async def fake_vision(self, request, user, model_id, png, snap, question):
        seen.update(model=model_id, png=png, q=question, layers=len(snap["layers"]))
        return "A map of the Netherlands; the WFS layer is not visible.", None

    monkeypatch.setattr(Tools, "_vision", fake_vision)
    calls = []
    kw = dict(__model__={"id": "gpt-4o"}, __request__=object(), __user__={"id": "u1"}, __metadata__=CHAT)
    out = run(t.look_at_map(question="is the WFS drawn?", __event_call__=fake_call(json.dumps(SNAP), calls=calls), **kw))
    assert '"png": true' in calls[0]["data"]["code"]
    assert seen == {"model": "gpt-4o", "png": "data:image/jpeg;base64,AAAA", "q": "is the WFS drawn?", "layers": 4}
    assert "What the screenshot shows (as seen by gpt-4o):\nA map of the Netherlands; the WFS layer is not visible." in out
    t.valves.vision_model = "my-vision"
    run(t.look_at_map(__event_call__=fake_call(json.dumps(SNAP)), **kw))
    assert seen["model"] == "my-vision"

    async def failing(self, *a):  # vision failures are reported, not raised
        return None, "model x could not describe the image"

    monkeypatch.setattr(Tools, "_vision", failing)
    out = run(t.look_at_map(__event_call__=fake_call(json.dumps(SNAP)), **kw))
    assert "No screenshot description: model x could not describe the image" in out
    snap = dict(SNAP)
    snap.pop("png")
    snap["pngError"] = "tainted canvas"
    out = run(t.look_at_map(__event_call__=fake_call(json.dumps(snap)), **kw))
    assert "No screenshot: tainted canvas." in out


def test_look_at_map_browser_failures():
    t = look_tools({"look_timeout": 1})
    out = run(t.look_at_map(__event_call__=fake_call(json.dumps({"ok": False, "reason": "map m1 is not on this page"})), __metadata__=CHAT))
    assert out.startswith("Could not look at map m1: map m1 is not on this page.") and "scroll to the map" in out
    assert "did not answer in time" in run(t.look_at_map(__event_call__=fake_call("{}", delay=2), __metadata__=CHAT))
    assert "could not reach the browser (socket closed)" in run(t.look_at_map(__event_call__=fake_call(RuntimeError("socket closed")), __metadata__=CHAT))
    assert "could not reach the browser" in run(t.look_at_map(__event_call__=fake_call("not json"), __metadata__=CHAT))
    assert "unknown error" in run(t.look_at_map(__event_call__=fake_call(None), __metadata__=CHAT))
    assert t.store.get("chat-A")["look"] is None


def test_vision_without_openwebui(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "open_webui.utils.chat", None)  # make the import fail, fast
    monkeypatch.setitem(sys.modules, "open_webui.models.users", None)
    t = mem_tools()
    assert run(t._vision(None, None, "", "data:", {}, "")) == (None, "no model id (set the vision_model valve)")
    assert run(t._vision(None, {"id": "u"}, "m", "data:", {}, ""))[1] == "Open WebUI's internal API is not available here"
    desc, err = run(t._vision(object(), {"id": "u"}, "m", "data:", {"layers": []}, ""))
    assert desc is None and "cannot import Open WebUI" in err


def test_store_dir_does_not_import_open_webui(monkeypatch):
    import sys
    monkeypatch.delitem(sys.modules, "open_webui.env", raising=False)
    monkeypatch.setenv("DATA_DIR", "/srv/owui-data")
    assert tool._store_dir().replace("\\", "/") == "/srv/owui-data/map_visualizer"
    assert "open_webui.env" not in sys.modules
    monkeypatch.delenv("DATA_DIR")
    assert tool._store_dir().endswith("map_visualizer")


def test_bridge_js_is_embedded_and_safe():
    spec = tool._normalise_spec({"title": "x"}, Tools.Valves())[0]
    html = tool._build_html(spec, Tools.Valves(), "m4", 7)
    assert '"mapId":"m4","mapVersion":7' in html
    assert "mv:call" in tool.BOOT_SCRIPT and "window.mvOps" in tool.MAP_SCRIPT
    assert "window.mvSnapshot" in tool.MAP_SCRIPT and "window.mvIdentify" in tool.MAP_SCRIPT
    assert "mv-legend" in tool.MAP_SCRIPT and "renderLegend" in tool.MAP_SCRIPT
    for tok in tool._FORBIDDEN_SRCDOC_TOKENS:
        assert tok not in tool._BRIDGE_JS


IDENT = {"ok": True, "version": 2, "lon": 4.9, "lat": 52.37, "zoom": 11.5, "panned": True,
         "queried": ["Parcels", "Cities", "Roads"],
         "hits": [{"layer": "Parcels", "type": "wms", "features": [{"id": 17, "owner": "Gemeente", "area": 1234.5, "empty": None}]},
                  {"layer": "Cities", "type": "geojson", "features": [{"name": "Amsterdam", "pop": 921000}, {"name": "Amstel"}]},
                  {"layer": "Roads", "type": "wms", "text": "A10 ring road"}]}


def test_query_map_identifies_features():
    t = look_tools({"look_timeout": 1})
    assert run(t.query_map(4.9, 52.37, __metadata__=CHAT)).startswith("query_map needs a live chat session")
    assert "no map in this chat" in run(t.query_map(4.9, 52.37, __metadata__={"chat_id": "none"}, __event_call__=fake_call("{}")))
    assert "must be numbers" in run(t.query_map("x", 1, __metadata__=CHAT, __event_call__=fake_call("{}")))
    assert "out of range" in run(t.query_map(500, 1, __metadata__=CHAT, __event_call__=fake_call("{}")))
    calls, (events, emitter) = [], collect()
    out = run(t.query_map(4.9, 52.37, layers=["Parcels", 2], __metadata__=CHAT, __event_emitter__=emitter,
                          __event_call__=fake_call(json.dumps(IDENT), calls=calls)))
    code = calls[0]["data"]["code"]
    assert '"op": "identify"' in code and '"lon": 4.9, "lat": 52.37' in code and '"layers": ["Parcels", "2"]' in code
    run(t.query_map(5, 100, __metadata__=CHAT, __event_call__=fake_call(json.dumps(IDENT), calls=calls)))
    assert '"lon": 100.0, "lat": 5.0' in calls[1]["data"]["code"]  # given as [lat, lon]: swapped
    assert out.startswith("Map m1 at lon 4.9, lat 52.37 (zoom 11.5, the map was panned there):")
    assert "  Parcels [wms]: 1 feature\n    id: 17; owner: Gemeente; area: 1234.5" in out
    assert "  Cities [geojson]: 2 features\n    name: Amsterdam; pop: 921000\n    name: Amstel" in out
    assert "  Roads [wms]: A10 ring road" in out
    assert "Nothing at this point in" not in out and "popup" in out
    assert events[-1]["data"] == {"description": "Identified on map m1: 4 results", "done": True}
    empty = dict(IDENT, hits=[], queried=["Parcels"])
    out = run(t.query_map(4.9, 52.37, __metadata__=CHAT, __event_call__=fake_call(json.dumps(empty))))
    assert "Nothing found at this point." in out and "Nothing at this point in: Parcels." in out
    out = run(t.query_map(4.9, 52.37, __metadata__=CHAT, __event_call__=fake_call(json.dumps(dict(empty, queried=[])))))
    assert "No layer on this map can be identified" in out
    out = run(t.query_map(4.9, 52.37, __metadata__=CHAT, __event_call__=fake_call("{}", delay=2)))
    assert out.startswith("Could not query map m1: the browser did not answer in time.")
