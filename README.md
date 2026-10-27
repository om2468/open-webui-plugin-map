# Map Visualizer for Open WebUI

Interactive [MapLibre GL](https://maplibre.org/) maps, rendered inline in Open WebUI chats. The model describes the map as a JSON layer spec; the tool draws it on a keyless basemap with a layer panel, a basemap gallery, click-to-identify popups, open building footprints, 3D terrain, a globe view, PNG export and a pop-out window. Users can then reorder, restyle and label layers, edit features and their attributes, and send the result back to the model.

The map is not a one-off picture. Each map has an id; the model changes it with small `update_map` calls, and with `look_at_map` it sees what actually rendered (layer errors, feature counts and a screenshot described by a vision model), so it can fix its own mistakes.

No API keys are needed. The default basemap is OpenStreetMap.

## What it does

| Feature | Detail |
| --- | --- |
| Many layer types | XYZ tiles, WMS, WMTS, WFS, OGC API Features, GeoJSON, vector tiles, PMTiles, Cloud Optimized GeoTIFF, georeferenced images, building footprints |
| Layer panel | Show or hide, opacity, drag to reorder, zoom to layer, per-layer error messages |
| Legend pane | Its own card at the bottom right, toggled from the toolbar: generated `colorBy` classes and WMS `GetLegendGraphic` images at native size, for the visible layers only |
| Vector styling | The model sets colour, outline, labels, extrusion, filters, and `colorBy` classification (graduated or categorical) with automatic legend |
| Style editor | Users can change a vector layer's colour, outline, line width, point size and labels (attribute, text size, colour) in the panel. Only the controls that fit the layer's geometry are shown. Server-styled layers (WMS, WMTS, XYZ, COG, images) offer opacity only |
| Feature editing | Edit features of GeoJSON, WFS and OGC API layers (move, reshape, add, delete points, lines, polygons, rectangles, circles) and their attributes, or draw a new sketch layer with the pencil button. Download the result as GeoJSON, or **Send to chat** to put it in your message box for the AI. Uses [Terra Draw](https://github.com/JamesLMilner/terra-draw), loaded only when you edit |
| Building footprints | Open data, no keys: OpenStreetMap buildings (OpenFreeMap) or [Overture Maps](https://overturemaps.org/) buildings (latest release, found automatically), as flat 2D footprints or extruded 3D |
| Identify | Click the map for feature attributes of vector layers and `GetFeatureInfo` of WMS layers. The model can do the same with `query_map(longitude, latitude)`, which shows the popup to you as well |
| Basemaps | 23 keyless options (OpenStreetMap, Esri, OpenFreeMap, USGS, NASA GIBS, PDOK) or any XYZ template or MapLibre style URL |
| 3D | Globe projection, terrain from open elevation tiles, extruded buildings, pitch and bearing |
| `inspect_ogc_service` | Reads WMS, WFS, WMTS and OGC API Features capabilities so the model uses real layer names instead of guessing |
| Living maps | `update_map` adds, removes, restyles, reorders, shows or hides layers and moves the view of an existing map by name or index. The model sends only the change; large GeoJSON is not resent. `describe_map` lists what is on a map |
| The model can look | `look_at_map` asks the user's browser for the map's state (per-layer load errors, tile failures, feature counts, how many features are in view) and a screenshot, which a vision model describes. The model then fixes problems with `update_map` |
| Export and pop-out | Save the current view as PNG, or open the map full-window in a new tab at the current view (downloads a standalone HTML file if popups are blocked) |
| Theme aware | Follows Open WebUI's dark or light theme (see setup) |

## Setup

1. In Open WebUI go to Workspace, then Tools, then **+ Create**.
2. Paste the contents of [`tool.py`](tool.py) and click **Save**.
3. Open the model you want to use (Workspace, then Models, then edit) and enable **Map Visualizer** under Tools.
4. Start a chat and ask for a map (see [example prompts](#example-prompts)).

Native (function) calling works and is recommended, because the layer spec is passed as a structured argument. Models need to be reasonably good at tool calls and JSON; small models tend to guess layer names, which `inspect_ogc_service` is there to prevent.

No Same-Origin setting is required. If you turn on **iframe Sandbox Allow Same Origin** (Settings, then Interface), the map can read Open WebUI's theme and follows its dark or light mode. Without it the map follows your operating system's setting instead.

To update, paste the new `tool.py` over the old one and save. The version is in the file header.

## How the model works with a map

| Function | What it does |
| --- | --- |
| `show_map` | Draws a new map and returns its id (`m1`, `m2`, ...). Each chat has its own maps |
| `update_map` | Changes a map: `add_layers`, `remove_layers`, `update_layers` (patches by name or 1-based index: `visible`, `opacity`, `style` merged with the existing style, `position` in the draw order, `rename`, or any layer key), plus title, basemap, centre, zoom, bounds, pitch, bearing, globe and terrain. The updated map is shown again as a new embed in the current reply |
| `describe_map` | Lists the map's layers, view and the result of the last `look_at_map`. Cheap, no browser round trip |
| `look_at_map` | Asks the open chat page for the map's live state and a screenshot. Returns, per layer: loaded or failed (with the error text), feature count and how many features are drawn in the current view, plus the view and a description of the screenshot by a vision model. Works only while the chat is open in the user's browser |
| `query_map` | Identifies what is at a longitude/latitude, like a click: attributes of the vector features there and the `GetFeatureInfo` answer of queryable WMS layers, optionally limited to named layers. The map pans there if the point is off screen and the popup is shown to the user. Raster tiles cannot be queried |
| `inspect_ogc_service` | Reads a service's capabilities so layer names are real |

The screenshot is a JPEG of the map canvas (at most 1200 px wide) sent to the model named in the `vision_model` valve, or to the chat's model when that valve is empty. That model must accept images; if it does not, `look_at_map` still returns the layer states and says the description failed. Set `vision_model` to `off` to skip the screenshot entirely. The screenshot stays inside your Open WebUI; it goes only to the model you configure.

Map state is saved per chat under `DATA_DIR/map_visualizer/` (the last 20 maps of each chat), so `update_map` works after a server restart. Updates always produce a new embed; the earlier embeds remain in the chat history as they were.

## Using the map panel

The model builds the map; the panel lets you adjust it without another prompt.

| Action | How |
| --- | --- |
| Show or hide | Tick box on the layer row |
| Reorder | Drag a row by its grip handle (⋮⋮). The line shows whether it lands above or below. Top of the list draws on top |
| Opacity | Click the layer name or its button. Raster layers (WMS, WMTS, XYZ, COG) show a half-filled circle and offer opacity only, since the server styles them |
| Restyle | Vector layers show a sliders button: colour (replaces any `colorBy` scheme), outline, width, point size |
| Label | Pick an attribute in **Label**, then set text size and colour. The picker appears only when the layer has attributes |
| Legend | The legend pane (bottom right) lists the legends of the visible layers; WMS legend images show at their native size and scroll. The toolbar's legend button hides or shows it, its header collapses it. It opens by default on maps at least 360 px tall and 600 px wide |
| Edit features | **Edit features** opens an edit bar: Select, Point, Line, Polygon, Rectangle, Circle, Delete, Save, Cancel. Drag a selected feature to move it, or its vertices to reshape it |
| Edit attributes | Draw or select a feature and an **Attributes** form appears top right. Change values, or type a name in **New attribute** and press Enter. Numbers and true/false values keep their type. Saved attributes become available to **Label** |
| Sketch | The pencil button in the toolbar starts a new, empty sketch layer in polygon mode |
| Download | **Download** saves the layer, with your edits, as a `.geojson` file |
| Send to chat | **Send to chat** puts the layer's GeoJSON into your message box (coordinates rounded to 6 decimals, about 30,000 characters at most). Add your question and send; the model can reuse it as an inline `geojson` layer |

Editing works for single Points, LineStrings and Polygons. Multi-part features (MultiPolygon and so on) are kept unchanged, and the edit bar says how many. Your order, visibility, opacity and edits survive the map being released off screen and the pop-out window. **Send to chat** is not offered in the pop-out, which is outside the chat.

## Layer types

Every layer accepts `name`, `type`, `visible` (default true), `opacity` (0 to 1), `minzoom`, `maxzoom`, `attribution`, `fit` (true zooms to this layer, false excludes it from auto-fit) and `bounds` `[west, south, east, north]`. Coordinates are always `[longitude, latitude]`. If `type` is omitted or is a common alias (`tiles`, `geotiff`, `features`, `mvt` and so on) the tool infers it from the URL and keys.

| Type | Key options |
| --- | --- |
| `xyz` | `url` or `tiles` with `{z}/{x}/{y}` (`{s}` or `{a-c}` subdomains work), `tileSize`, `scheme: "tms"`, `sourceMaxzoom` |
| `wms` | `url`, `layers`, `styles`, `format`, `transparent`, `version` (1.3.0), `params` (extra GetMap parameters such as `TIME`), `queryable`, `infoFormat`, `queryLayers`, `legend`, `legendUrl` |
| `wmts` | `url` as a REST template (`{TileMatrix}/{TileRow}/{TileCol}`, or `{z}/{y}/{x}`) or a KVP endpoint with `layer`, `tileMatrixSet`, `styleName`, `format`, plus `matrixPrefix`, `time`, `dimensions` |
| `wfs` | `url`, `typeName`, `version` (2.0.0), `maxFeatures` (2000), `cqlFilter`, `outputFormat`, `srsName`, `axisOrder` (`auto`, `lonlat`, `latlon`), `strategy: "bbox"`, `loadMinzoom` (10) |
| `ogcapi` | `url` to a `/collections/{id}` or `/items` endpoint (or the API root plus `collection`), `limit` (1000), `strategy: "bbox"`, `params` |
| `geojson` | `data` (inline FeatureCollection, Feature or geometry) or `url` |
| `vectortiles` | `url` (TileJSON) or `tiles` template with `sourceLayer` (required for templates, optional for TileJSON), `sourceMaxzoom` |
| `pmtiles` | `url` to a `.pmtiles` archive, vector or raster; `sourceLayer` optional |
| `cog` | `url` to a Cloud Optimized GeoTIFF, `rescale` (`"min,max"`), `colormap`, `bidx` (for example `[1,2,3]`), `nodata`, `expression`, `titiler` (override the endpoint) |
| `image` | `url` plus `coordinates` (`[[TL],[TR],[BR],[BL]]`) or `bounds` |
| `buildings` | Open building footprints; no `url` needed. `source`: `openfreemap` (OpenStreetMap, default) or `overture` (Overture Maps; the latest release is looked up from the Overture STAC catalogue, or pin one with `release`). `mode`: `3d` (extruded by height, default; tilts the camera if you did not set a pitch) or `2d` (flat footprints). Type `footprints` is shorthand for 2D. Appears from zoom 13 (`minzoom`); click a building for its attributes |

`wfs` and `ogcapi` load the whole result once by default. Set `strategy: "bbox"` for large datasets: the tool then reloads for the current view whenever the map moves (WFS only above `loadMinzoom`).

### Vector styling

Applies to `geojson`, `wfs`, `ogcapi`, `vectortiles` and `pmtiles`. Put these in a layer's `style` object.

| Key | Meaning |
| --- | --- |
| `color` | Base colour for the layer. Layers get distinct default colours otherwise |
| `fillColor`, `fillOpacity`, `strokeColor`, `width`, `outlineWidth`, `dash` | Polygon fill and outline, line width and dash array such as `[2,2]` |
| `radius`, `strokeWidth`, `pointOpacity` | Point size and outline |
| `label`, `labelSize`, `labelColor`, `labelHalo` | Label each feature with a property |
| `extrude`, `extrudeScale` | Extrude polygons by a property name or a fixed height in metres |
| `filter` | A MapLibre filter expression |
| `colorBy` | Data-driven colour, below |

`colorBy` takes a field name or an object:

| Key | Meaning |
| --- | --- |
| `field` | Property to classify (required) |
| `type` | `graduated` (default for numeric fields, or when `breaks` is given) or `categorical` |
| `scheme`, `classes` | Graduated classing: `quantile` (default) or `equal`, and 2 to 9 classes (default 5) |
| `breaks` | Explicit class breaks, for example `[10, 50, 200]` |
| `colormap` | `viridis`, `plasma`, `magma`, `inferno`, `cividis`, `YlOrRd`, `YlGnBu`, `YlGn`, `Blues`, `Greens`, `Reds`, `Oranges`, `Purples`, `Greys`, `RdYlGn`, `RdYlBu`, `RdBu`, `Spectral`, `terrain`. Add `_r` to reverse |
| `colors` | Your own colour list (graduated needs one more colour than breaks) |
| `mapping`, `categories` | Categorical: explicit value to colour map, or a list of values to colour in order (up to 24 categories are coloured, others grey) |
| `title` | Legend title |

`popup` controls click-to-identify: `true` (all attributes, default), `false`, or a list of field names.

Server-side checks reject layers that have no URL, use non-http(s) URLs or are not on the allowlist, and report them back to the model so it can correct itself.

## Basemaps

Set with `basemap`, or change in the panel. Names are case-insensitive. You can also pass any XYZ template (containing `{z}`) or a MapLibre style URL.

| Provider | Basemaps |
| --- | --- |
| OpenStreetMap | `OpenStreetMap` (default), `OpenStreetMap.HOT`, `OpenTopoMap`, `CyclOSM` |
| Esri | `Esri.WorldImagery`, `Esri.Hybrid` (imagery plus labels), `Esri.WorldTopoMap`, `Esri.WorldStreetMap`, `Esri.WorldGrayCanvas`, `Esri.WorldShadedRelief`, `Esri.OceanBasemap` |
| OpenFreeMap (vector) | `OpenFreeMap.Liberty`, `.Bright`, `.Positron`, `.Dark`, `.Fiord` |
| Agencies | `USGS.USImagery`, `USGS.USTopo`, `NASAGIBS.BlueMarble`, `NASAGIBS.EarthAtNight`, `PDOK.BRT` and `PDOK.Luchtfoto` (Netherlands only) |
| Other | `None` (blank background) |

Please respect each provider's usage policy. The public OpenStreetMap tile servers in particular are not meant for heavy traffic.

## Valves

Set by an admin under Workspace, then Tools, then the gear icon on Map Visualizer.

| Valve | Default | Purpose |
| --- | --- | --- |
| `network_policy` | `open` | `open` lets the map load from any host. `allowlist` restricts the map (by CSP) and the server-side checks to `allowed_hosts` |
| `allowed_hosts` | Built-in basemap hosts, `unpkg.com`, `titiler.xyz`, terrain host | Comma-separated hosts for `allowlist`; wildcards such as `*.example.com` work |
| `default_basemap` | `OpenStreetMap` | Basemap used when the model does not choose one |
| `default_height` | `520` | Map height in pixels (requests are clamped to 240 to 1200) |
| `maplibre_js_url` | `https://unpkg.com/maplibre-gl@5.24.0/dist/maplibre-gl.js` | MapLibre GL JS (5.x UMD build) |
| `maplibre_css_url` | `https://unpkg.com/maplibre-gl@5.24.0/dist/maplibre-gl.css` | MapLibre GL CSS |
| `pmtiles_js_url` | `https://unpkg.com/pmtiles@4.4.1/dist/pmtiles.js` | PMTiles library, loaded only for maps that use PMTiles |
| `terra_draw_js_url`, `terra_draw_adapter_js_url` | `terra-draw@1.35.0` and `terra-draw-maplibre-gl-adapter@1.4.1` on unpkg | Feature editor, loaded only when someone edits or draws |
| `titiler_endpoint` | `https://titiler.xyz` | TiTiler server used to tile COG layers |
| `terrain_tiles` | AWS open Terrarium elevation tiles | Elevation tiles for 3D terrain |
| `glyphs_url` | OpenFreeMap font PBFs | Glyphs (fonts) for labels on raster basemaps |
| `label_font` | `Noto Sans Regular` | Font stack name; must exist at `glyphs_url` |
| `allow_private_networks` | `false` | Let `inspect_ogc_service` reach private or internal addresses |
| `request_timeout` | `20` | Timeout in seconds for `inspect_ogc_service` |
| `vision_model` | empty | Model that `look_at_map` sends the screenshot to. Empty = the chat's model (must accept images); `off` = layer states only, no screenshot |
| `look_timeout` | `45` | Seconds `look_at_map` waits for the browser to answer |

## Security model

The map runs inside Open WebUI's sandboxed iframe with a Content Security Policy (CSP) set by the tool.

| Level | CSP | Trade-off |
| --- | --- | --- |
| `open` (default) | Blocks plugins, forms and `<base>`; does not restrict where scripts, images or data requests go | Any WMS, WFS, tile or GeoJSON host works. The cost is that a map can make requests to any host. A prompt-injected or malicious spec could encode chat data into a URL (for example an image or tile URL) and send it out. Only use this where you trust the model's inputs and your users |
| `allowlist` | `default-src 'self'` plus script, style, image, connect and font sources limited to `allowed_hosts` and the hosts in your MapLibre, PMTiles and TiTiler valves | Exfiltration to other hosts is blocked by the browser. You must list every service your users need. Layers and basemaps on unlisted hosts are rejected before the map is drawn, and `inspect_ogc_service` refuses unlisted hosts |

In both modes the page loads MapLibre from the URL in the valves, which is third-party code unless you self-host it (below).

**`inspect_ogc_service` and SSRF.** This is the only part that makes requests from your server. It accepts only absolute http(s) URLs, resolves the host and refuses anything that is not a public address (loopback, link-local, private ranges), connects to exactly the address it checked (so a DNS answer that changes between check and connect cannot redirect it to an internal host), re-checks every redirect, and caps the response at 8 MB. When the server reaches the internet through a proxy, the proxy resolves the host and only the up-front check applies. Set `allow_private_networks` only if you need to inspect services on your internal network, and understand that this lets the model, and so anyone who can prompt it, make the Open WebUI server fetch internal URLs.

### Self-hosting MapLibre (air-gapped installs)

1. Download these files:
   - `maplibre-gl.js` and `maplibre-gl.css` from `https://unpkg.com/maplibre-gl@5.24.0/dist/`
   - `pmtiles.js` from `https://unpkg.com/pmtiles@4.4.1/dist/` (only if you use PMTiles)
2. Put them in Open WebUI's static directory, for example `backend/open_webui/static/maplibre/` (in the Docker image: `/app/backend/open_webui/static/maplibre/`). They are then served at `/static/maplibre/...`.
3. Set the valves:
   - `maplibre_js_url` to `/static/maplibre/maplibre-gl.js`
   - `maplibre_css_url` to `/static/maplibre/maplibre-gl.css`
   - `pmtiles_js_url` to `/static/maplibre/pmtiles.js`
   - `terra_draw_js_url` and `terra_draw_adapter_js_url` to your copies of `terra-draw.umd.js` and `terra-draw-maplibre-gl-adapter.umd.js` (only if you want feature editing)
4. Set `network_policy` to `allowlist` and list your internal tile, WMS and WFS hosts in `allowed_hosts`. Set `default_basemap` to your own tile URL or style URL, and point `glyphs_url`, `terrain_tiles` and `titiler_endpoint` at internal servers if you use labels, terrain or COGs.

Relative URLs resolve against the Open WebUI origin.

## Limitations

- WMS and WMTS layers must be available in EPSG:3857 (Web Mercator). `inspect_ogc_service` shows this per layer.
- WMTS tile matrix ids must be plain zoom numbers, optionally with a prefix (`0`, `1`, `2` or `EPSG:3857:0`, `EPSG:3857:1`). Zero-padded ids such as `00` and `01` are not supported; use the service's WMS instead.
- Services need to send CORS headers (`Access-Control-Allow-Origin`) because the browser fetches them directly. If a layer shows a red error or tile failures, this is the usual cause.
- WFS layers need GeoJSON output (`application/json`). Services that only offer GML will not work.
- WMS `GetFeatureInfo` on click assumes the map is not rotated or pitched.
- COG layers go through the public `titiler.xyz` demo server by default, which is rate-limited and not for production use. Run your own TiTiler and set `titiler_endpoint` for anything serious. The COG itself must be reachable by that server and send CORS headers.
- Every `update_map` shows the updated map as a new embed; the embed from the earlier reply is not changed in place.
- `look_at_map` and `query_map` need the chat open in a browser. It does not work from the API or while the user has navigated away, and after a page reload the user may need to scroll to the map so it starts.
- Large vector datasets are slow. Use `strategy: "bbox"`, `maxFeatures` or vector tiles.

## Troubleshooting

<details>
<summary>The map area is blank or says it could not load MapLibre GL</summary>

The browser could not fetch the script from `maplibre_js_url`. Check that the host is reachable from the user's browser (not just the server), that a firewall or ad blocker is not blocking `unpkg.com`, or self-host the files. In `allowlist` mode the valve hosts are added to the CSP automatically.
</details>

<details>
<summary>A layer shows a red error or "Some tiles failed to load"</summary>

Open the layer panel. HTTP 400 or a service exception usually means a wrong layer name, so ask the model to call `inspect_ogc_service` and retry. A network or CORS message means the server does not allow browser access. A WMS layer without EPSG:3857 or a WFS without JSON output cannot be shown.
</details>

<details>
<summary>The model keeps inventing layer names</summary>

Tell it to use `inspect_ogc_service` first, or enable the tool for a more capable model. Passing `search` narrows large capabilities documents.
</details>

<details>
<summary>The model says a layer was rejected</summary>

The tool returns a list of rejected layers. Typical reasons: missing `url`, an unknown `type`, a non-http(s) URL, or in `allowlist` mode a host that is not in `allowed_hosts`.
</details>

<details>
<summary>The map is light while Open WebUI is dark (or the reverse)</summary>

Without "iframe Sandbox Allow Same Origin" the map follows the operating system's colour scheme, not Open WebUI's theme. Enable that setting if you want them to match.
</details>

<details>
<summary>inspect_ogc_service says a host resolves to a non-public address</summary>

This is the SSRF guard. Enable `allow_private_networks` only if you intend the tool to reach internal services.
</details>

<details>
<summary>A map says "Loading map…" until I scroll to it, or reloads after I scroll back</summary>

That is deliberate. Browsers allow only about 16 live WebGL maps per page, so each map starts when it first scrolls into view and is released after a minute off screen. When you scroll back it rebuilds at the same view and basemap, with your layer order, visibility, opacity and saved edits. Style and label changes made in the panel are not kept. An edit session that is still open is saved automatically when the map is released.
</details>

<details>
<summary>The map is the wrong height or cut off</summary>

Pass `height` (240 to 1200) or change `default_height`. Narrow chat windows collapse the layer panel automatically; click its header to open it.
</details>

<details>
<summary>"Could not load the feature editor"</summary>

The browser could not fetch Terra Draw from `terra_draw_js_url`. Check that `unpkg.com` is reachable from the browser, or self-host both Terra Draw files and set the two valves.
</details>

<details>
<summary>look_at_map says it could not look at the map</summary>

The tool asks the browser that is showing the chat for the map. It fails when the chat is not open, when the map's embed is not on the page (a different chat, or the message was deleted), or when the map has not started because it is off screen after a reload: scroll to it and ask again. If the chat's model does not accept images you still get the layer states; set `vision_model` to a vision-capable model, or to `off`.
</details>

<details>
<summary>Send to chat does nothing</summary>

It fills the message box of the chat the map belongs to, so it only works in the chat itself, not in the pop-out window. Older Open WebUI versions may ignore the request; use **Download** instead and attach the file.
</details>

## Example prompts

- "Show me a map of the Dutch provinces from the PDOK CBS WMS on the PDOK background map."
- "Find a NASA GIBS layer for night lights and show it on a globe."
- "Map the windmills from the pygeoapi demo and colour them by type."
- "Plot these five offices on a map, label them and give each a colour by region." (paste the coordinates)
- "Show 3D buildings in central Amsterdam with terrain on."
- "Show Overture building footprints around Westminster on aerial imagery."
- "Look at this WFS, tell me what layers it has and map the largest one: `<url>`"
- "Show this Cloud Optimized GeoTIFF with a viridis colour map, rescaled 0 to 255: `<url>`"

Complete, tested `show_map` arguments are in [`examples/`](examples/).

## Changelog

**0.4.0**

- `query_map`: the model identifies features at a location (vector attributes and WMS `GetFeatureInfo`), with the popup shown to the user.
- Legend pane: legends moved out of the layer panel into their own card at the bottom right, WMS legend images at native size, visible layers only, toggled from the toolbar.
- Pop-out window sends no referrer, so OpenStreetMap tiles no longer return 403 "Access blocked" there.
- `look_at_map` reports tile failures as problems only for visible layers.

**0.3.0**
- Maps have ids and live per chat. `update_map` changes an existing map (layers by name or index, style merging, reordering, view) and shows it again; the model no longer resends the whole spec.
- `look_at_map`: the model sees the map as rendered, with per-layer errors, feature counts, features in view, and a vision-model description of a screenshot. New valves `vision_model` and `look_timeout`.
- `describe_map` lists a map's layers and view.
- Map state is kept under `DATA_DIR/map_visualizer/`.

**0.2.0**
- Feature editing with Terra Draw: move, reshape, add and delete features, plus a sketch layer from the toolbar.
- Attribute form for the selected or newly drawn feature; new attributes become label options.
- Download a layer as GeoJSON, or Send to chat to hand it to the model.
- Drag-and-drop reordering with a grip handle and above/below drop indicator (replaces the Up and Down buttons).
- Style editor shows only controls that fit the layer: raster layers get opacity only, and point size appears only for layers with points. The Label picker is hidden when there are no attributes.
- Layer order and edits survive release off screen and the pop-out window.

**0.1.0**
- First release: layer types, keyless basemaps, building footprints, `inspect_ogc_service`, style editor, pop-out, lazy start and release of maps.

## Acknowledgements

- [Classic298's Inline Visualizer](https://github.com/Classic298/open-webui-plugins/tree/main/inline-visualizer-v2) showed how to render rich inline content in Open WebUI, and this README follows its structure.
- [Qiusheng Wu](https://github.com/giswqs) and the OpenGeos community: the layer vocabulary and tool design draw on [leafmap](https://github.com/opengeos/leafmap) (its `maplibregl` API), [GeoAgent](https://github.com/opengeos/GeoAgent) (map tools for agents), [GeoLibre](https://github.com/opengeos/GeoLibre), [maplibre-gl-layer-control](https://github.com/opengeos/maplibre-gl-layer-control) and [maplibre-gl-basemap-control](https://github.com/opengeos/maplibre-gl-basemap-control).
- [MapLibre GL JS](https://maplibre.org/), [PMTiles](https://github.com/protomaps/PMTiles), [TiTiler](https://github.com/developmentseed/titiler), [OpenFreeMap](https://openfreemap.org/) and [Overture Maps](https://docs.overturemaps.org/attribution) (building footprints © OpenStreetMap and Overture Maps Foundation).
- The basemap providers listed above. Check each provider's terms and attribution requirements.
