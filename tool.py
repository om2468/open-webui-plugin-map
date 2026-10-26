"""
title: Map Visualizer
author: om2468
author_url: https://github.com/om2468
version: 0.1.0
required_open_webui_version: 0.6.0
description: Renders interactive MapLibre maps inline in chat. The model builds the map from a JSON layer spec (XYZ/WMTS tiles, WMS, WFS, OGC API Features, GeoJSON, vector tiles, PMTiles, COG, images, 3D buildings) on top of keyless open basemaps. Includes inspect_ogc_service to look up real WMS/WFS/WMTS layer names.
"""

import asyncio
import ipaddress
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Literal, Optional

from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

_MV_BUILD = "0.1.0"

# ---------------------------------------------------------------------------
# Basemap catalogue: keyless providers only (no API tokens required).
# Raster entries carry XYZ templates; "style" entries are MapLibre style URLs.
# ---------------------------------------------------------------------------

_OSM = "&copy; OpenStreetMap contributors"
_ESRI = "Tiles &copy; Esri"


def _abc(template: str, subs: str = "abc") -> list:
    return [template.replace("{s}", s) for s in subs]


BASEMAPS = [
    # OpenStreetMap family
    {"id": "OpenStreetMap", "group": "OpenStreetMap", "type": "raster",
     "tiles": ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"], "maxzoom": 19, "attribution": _OSM},
    {"id": "OpenStreetMap.HOT", "group": "OpenStreetMap", "type": "raster",
     "tiles": _abc("https://{s}.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png"), "maxzoom": 19,
     "attribution": _OSM + ", Humanitarian OpenStreetMap Team, OpenStreetMap France"},
    {"id": "OpenTopoMap", "group": "OpenStreetMap", "type": "raster",
     "tiles": _abc("https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png"), "maxzoom": 17,
     "attribution": _OSM + ", SRTM | Style &copy; OpenTopoMap (CC-BY-SA)"},
    {"id": "CyclOSM", "group": "OpenStreetMap", "type": "raster",
     "tiles": _abc("https://{s}.tile-cyclosm.openstreetmap.fr/cyclosm/{z}/{x}/{y}.png"), "maxzoom": 20,
     "attribution": _OSM + " | CyclOSM"},
    # Esri
    {"id": "Esri.WorldImagery", "group": "Esri", "type": "raster",
     "tiles": ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"], "maxzoom": 19,
     "attribution": _ESRI + ", Maxar, Earthstar Geographics, and the GIS User Community"},
    {"id": "Esri.Hybrid", "group": "Esri", "type": "raster",
     "tiles": ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],
     "overlay": ["https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}"],
     "maxzoom": 19, "attribution": _ESRI + ", Maxar, Earthstar Geographics"},
    {"id": "Esri.WorldTopoMap", "group": "Esri", "type": "raster",
     "tiles": ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}"], "maxzoom": 19, "attribution": _ESRI},
    {"id": "Esri.WorldStreetMap", "group": "Esri", "type": "raster",
     "tiles": ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}"], "maxzoom": 19, "attribution": _ESRI},
    {"id": "Esri.WorldGrayCanvas", "group": "Esri", "type": "raster",
     "tiles": ["https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}"], "maxzoom": 16, "attribution": _ESRI + ", HERE, Garmin"},
    {"id": "Esri.WorldShadedRelief", "group": "Esri", "type": "raster",
     "tiles": ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Shaded_Relief/MapServer/tile/{z}/{y}/{x}"], "maxzoom": 13, "attribution": _ESRI},
    {"id": "Esri.OceanBasemap", "group": "Esri", "type": "raster",
     "tiles": ["https://server.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Ocean_Base/MapServer/tile/{z}/{y}/{x}"], "maxzoom": 13, "attribution": _ESRI + ", GEBCO, NOAA"},
    # OpenFreeMap vector styles
    {"id": "OpenFreeMap.Liberty", "group": "OpenFreeMap (vector)", "type": "style",
     "url": "https://tiles.openfreemap.org/styles/liberty", "thumb": "#e9e4d8"},
    {"id": "OpenFreeMap.Bright", "group": "OpenFreeMap (vector)", "type": "style",
     "url": "https://tiles.openfreemap.org/styles/bright", "thumb": "#f3efe6"},
    {"id": "OpenFreeMap.Positron", "group": "OpenFreeMap (vector)", "type": "style",
     "url": "https://tiles.openfreemap.org/styles/positron", "thumb": "#f2f2f2"},
    {"id": "OpenFreeMap.Dark", "group": "OpenFreeMap (vector)", "type": "style",
     "url": "https://tiles.openfreemap.org/styles/dark", "thumb": "#2b2b2b"},
    {"id": "OpenFreeMap.Fiord", "group": "OpenFreeMap (vector)", "type": "style",
     "url": "https://tiles.openfreemap.org/styles/fiord", "thumb": "#45516e"},
    # Agencies
    {"id": "USGS.USImagery", "group": "Agencies", "type": "raster",
     "tiles": ["https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}"], "maxzoom": 16, "attribution": "USGS The National Map"},
    {"id": "USGS.USTopo", "group": "Agencies", "type": "raster",
     "tiles": ["https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{z}/{y}/{x}"], "maxzoom": 16, "attribution": "USGS The National Map"},
    {"id": "NASAGIBS.BlueMarble", "group": "Agencies", "type": "raster",
     "tiles": ["https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/BlueMarble_ShadedRelief_Bathymetry/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpeg"],
     "maxzoom": 8, "attribution": "NASA GIBS / ESDIS"},
    {"id": "NASAGIBS.EarthAtNight", "group": "Agencies", "type": "raster",
     "tiles": ["https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/VIIRS_CityLights_2012/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpeg"],
     "maxzoom": 8, "attribution": "NASA GIBS / ESDIS"},
    {"id": "PDOK.BRT", "group": "Agencies", "type": "raster",
     "tiles": ["https://service.pdok.nl/brt/achtergrondkaart/wmts/v2_0/standaard/EPSG:3857/{z}/{x}/{y}.png"],
     "maxzoom": 19, "attribution": "Kadaster / PDOK (Netherlands only)", "thumbTile": "7/65/42"},
    {"id": "PDOK.Luchtfoto", "group": "Agencies", "type": "raster",
     "tiles": ["https://service.pdok.nl/hwh/luchtfotorgb/wmts/v1_0/Actueel_orthoHR/EPSG:3857/{z}/{x}/{y}.jpeg"],
     "maxzoom": 19, "attribution": "Beeldmateriaal.nl / PDOK (Netherlands only)", "thumbTile": "7/65/42"},
    {"id": "None", "group": "Other", "type": "none", "thumb": "#dfe6ea"},
]
_BASEMAP_IDS = {b["id"].lower(): b["id"] for b in BASEMAPS}
# CARTO now watermarks keyless tiles ("API KEY REQUIRED"); models still ask for these names
_BASEMAP_ALIASES = {
    "cartodb.positron": "OpenFreeMap.Positron", "cartodb.positronnolabels": "OpenFreeMap.Positron",
    "cartodb.darkmatter": "OpenFreeMap.Dark", "cartodb.voyager": "OpenFreeMap.Liberty",
    "osm": "OpenStreetMap", "satellite": "Esri.WorldImagery", "imagery": "Esri.WorldImagery",
}
_BASEMAP_IDS.update(_BASEMAP_ALIASES)

GLYPHS_URL = "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf"
TERRAIN_TILES = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
BUILDINGS_TILES = "https://tiles.openfreemap.org/planet"
# Overture deletes old releases, so the map resolves the latest one from the STAC catalogue
OVERTURE_CATALOG = "https://stac.overturemaps.org/catalog.json"
OVERTURE_BUILDINGS = "https://overturemaps-extras-us-west-2.s3.us-west-2.amazonaws.com/tiles/{release}/buildings.pmtiles"

_DEFAULT_ALLOWED_HOSTS = (
    "unpkg.com, tile.openstreetmap.org, *.tile.openstreetmap.fr, *.tile.opentopomap.org, "
    "*.tile-cyclosm.openstreetmap.fr, server.arcgisonline.com, "
    "tiles.openfreemap.org, basemap.nationalmap.gov, gibs.earthdata.nasa.gov, service.pdok.nl, "
    "s3.amazonaws.com, titiler.xyz, stac.overturemaps.org, "
    "overturemaps-extras-us-west-2.s3.us-west-2.amazonaws.com"
)

LAYER_TYPES = (
    "xyz", "wms", "wmts", "wfs", "ogcapi", "geojson", "vectortiles",
    "pmtiles", "cog", "image", "buildings",
)
_TYPE_ALIASES = {
    "tile": "xyz", "tiles": "xyz", "raster": "xyz", "tms": "xyz",
    "ogc-api": "ogcapi", "ogcapi-features": "ogcapi", "features": "ogcapi",
    "vector": "geojson", "json": "geojson",
    "mvt": "vectortiles", "vector-tiles": "vectortiles", "vectortile": "vectortiles",
    "geotiff": "cog", "tif": "cog", "3d-buildings": "buildings", "buildings3d": "buildings",
    "building": "buildings", "footprints": "buildings", "building-footprints": "buildings",
}

# ---------------------------------------------------------------------------
# Iframe CSS
# ---------------------------------------------------------------------------

MAP_CSS = """
:root {
  --mv-bg: rgba(255,255,255,.96); --mv-fg: #1f2937; --mv-muted: #6b7280;
  --mv-border: rgba(0,0,0,.12); --mv-hover: rgba(0,0,0,.05); --mv-accent: #2563eb;
  --mv-danger: #dc2626; --mv-shadow: 0 2px 10px rgba(0,0,0,.15);
  --mv-font: system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;
}
[data-theme="dark"] {
  --mv-bg: rgba(30,32,36,.95); --mv-fg: #e5e7eb; --mv-muted: #9ca3af;
  --mv-border: rgba(255,255,255,.14); --mv-hover: rgba(255,255,255,.07); --mv-accent: #60a5fa;
  --mv-danger: #f87171; --mv-shadow: 0 2px 12px rgba(0,0,0,.5);
}
html, body { margin: 0; padding: 0; background: transparent; font-family: var(--mv-font); overflow: hidden; }
/* border-box: a 100%-wide wrap plus its border would overflow and add scrollbars to the iframe */
#mv-wrap { position: relative; width: 100%; box-sizing: border-box; border-radius: 12px; overflow: hidden;
  border: 1px solid var(--mv-border); }
#mv-map { position: absolute; inset: 0; }
.mv-card { background: var(--mv-bg); color: var(--mv-fg); border: 1px solid var(--mv-border);
  border-radius: 10px; box-shadow: var(--mv-shadow); font-size: 12px; }
#mv-panel { position: absolute; top: 10px; left: 10px; z-index: 3; width: 260px;
  max-height: calc(100% - 50px); display: flex; flex-direction: column; }
#mv-panel.collapsed { width: auto; }
#mv-panel.collapsed .mv-body { display: none; }
.mv-head { display: flex; align-items: center; gap: 6px; padding: 8px 10px; cursor: pointer;
  font-weight: 600; font-size: 13px; user-select: none; }
.mv-head .mv-title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mv-body { overflow-y: auto; overflow-x: hidden; border-top: 1px solid var(--mv-border); }
.mv-row .mv-btn.on { color: var(--mv-accent); }
.mv-sym span { width: 48px; flex: none; }
.mv-sym input[type=range] { flex: 1; min-width: 0; }
.mv-sym input[type=color] { width: 30px; height: 20px; padding: 0; border: 1px solid var(--mv-border); border-radius: 4px;
  background: none; cursor: pointer; }
.mv-sec { padding: 6px 10px 8px; }
.mv-sec + .mv-sec { border-top: 1px solid var(--mv-border); }
.mv-label { font-size: 10px; text-transform: uppercase; letter-spacing: .06em; color: var(--mv-muted);
  margin: 2px 0 6px; }
.mv-row { display: flex; align-items: center; gap: 6px; padding: 3px 2px; border-radius: 6px; }
.mv-row:hover { background: var(--mv-hover); }
.mv-row input[type=checkbox] { margin: 0; accent-color: var(--mv-accent); cursor: pointer; }
.mv-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; cursor: pointer; }
.mv-sw { width: 12px; height: 12px; border-radius: 3px; flex: none; border: 1px solid var(--mv-border); }
.mv-sw.raster { background: linear-gradient(135deg,#9bc4e2,#c8e6a0 50%,#e8d3a0); }
.mv-btn { background: transparent; border: 0; color: var(--mv-muted); cursor: pointer; padding: 2px 4px;
  border-radius: 5px; font: inherit; line-height: 1; }
.mv-btn:hover { color: var(--mv-fg); background: var(--mv-hover); }
.mv-btn svg { width: 14px; height: 14px; display: block; fill: none; stroke: currentColor; stroke-width: 1.8;
  stroke-linecap: round; stroke-linejoin: round; }
.mv-detail { padding: 2px 4px 6px 24px; display: none; }
.mv-detail.open { display: block; }
.mv-detail input[type=range] { width: 100%; accent-color: var(--mv-accent); }
.mv-legend-item { display: flex; align-items: center; gap: 6px; margin: 2px 0; color: var(--mv-muted); }
.mv-legend img { max-width: 100%; background: #fff; border-radius: 4px; margin-top: 4px; }
.mv-err { color: var(--mv-danger); font-size: 11px; padding: 0 4px 4px 24px; word-break: break-word; }
.mv-spin { width: 10px; height: 10px; border: 2px solid var(--mv-border); border-top-color: var(--mv-accent);
  border-radius: 50%; animation: mvspin .8s linear infinite; flex: none; }
@keyframes mvspin { to { transform: rotate(360deg); } }
.mv-bm-current { display: flex; align-items: center; gap: 8px; width: 100%; padding: 4px; border-radius: 8px;
  border: 1px solid var(--mv-border); background: transparent; color: inherit; font: inherit; cursor: pointer; text-align: left; }
.mv-bm-current:hover { background: var(--mv-hover); }
.mv-thumb { width: 34px; height: 34px; border-radius: 6px; flex: none; background-size: cover;
  background-position: center; border: 1px solid var(--mv-border); }
/* minmax(0,1fr): long basemap names must not widen the columns past the panel */
.mv-bm-grid { display: none; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 6px; margin-top: 8px; }
.mv-bm-grid.open { display: grid; }
.mv-bm-group { grid-column: 1 / -1; font-size: 10px; color: var(--mv-muted); margin-top: 4px; }
.mv-bm-opt { display: flex; flex-direction: column; align-items: center; gap: 3px; padding: 3px; border-radius: 8px; min-width: 0;
  border: 1px solid transparent; background: transparent; color: inherit; font: inherit; font-size: 10px; cursor: pointer; }
.mv-bm-opt .mv-thumb { width: 100%; height: 44px; }
.mv-bm-opt span { max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mv-bm-opt:hover { background: var(--mv-hover); }
.mv-bm-opt.active { border-color: var(--mv-accent); }
#mv-tools { position: absolute; top: 10px; right: 50px; z-index: 3; display: flex; gap: 2px; padding: 3px; }
#mv-tools .mv-btn { padding: 5px; }
#mv-tools .mv-btn.on { color: var(--mv-accent); }
#mv-coords { position: absolute; bottom: 8px; left: 50%; transform: translateX(-50%); z-index: 2;
  padding: 2px 8px; font-variant-numeric: tabular-nums; font-size: 11px; pointer-events: none; }
#mv-coords:empty { display: none; }
.maplibregl-popup-content { background: var(--mv-bg); color: var(--mv-fg); border-radius: 8px;
  padding: 8px 10px; font-family: var(--mv-font); font-size: 12px; max-height: 260px; overflow: auto; }
.maplibregl-popup-tip { border-top-color: var(--mv-bg) !important; border-bottom-color: var(--mv-bg) !important; }
.maplibregl-popup-close-button { color: var(--mv-muted); }
.mv-pop h4 { margin: 0 0 4px; font-size: 12px; }
.mv-pop h4:not(:first-child) { margin-top: 10px; }
.mv-pop table { border-collapse: collapse; width: 100%; }
.mv-pop td { padding: 2px 6px 2px 0; vertical-align: top; border-bottom: 1px solid var(--mv-border); }
.mv-pop td:first-child { color: var(--mv-muted); white-space: nowrap; }
.mv-pop iframe { border: 0; width: 280px; height: 160px; background: #fff; }
#mv-msg { position: absolute; inset: 0; display: flex; align-items: flex-start; justify-content: center;
  padding: 48px 24px 0; color: var(--mv-muted); font-size: 13px; z-index: 1; text-align: center; }
#mv-msg.mv-fail { color: var(--mv-danger); }
@media (max-width: 520px) { #mv-panel { width: 210px; } }
"""

# ---------------------------------------------------------------------------
# Iframe script
#
# !! SRCDOC SAFETY !!  The page is delivered through an iframe srcdoc. Do NOT
# write the literal tokens "<!--", "-->", "<script" or "</script" anywhere in
# this body (not even in comments): they flip the HTML parser into
# script-data-escape mode and silently truncate the script.
# ---------------------------------------------------------------------------

MAP_SCRIPT = r"""
(function () {
'use strict';
var CFG = JSON.parse(document.getElementById('mv-config').textContent);
var SPEC = CFG.spec;
var LAYER_COLORS = ['#2563eb', '#dc2626', '#16a34a', '#d97706', '#7c3aed', '#0891b2', '#db2777', '#65a30d', '#ea580c', '#4f46e5'];
var CATEGORICAL = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf', '#aec7e8', '#ffbb78'];
var COLORMAPS = {
  viridis: ['#440154', '#3b528b', '#21918c', '#5ec962', '#fde725'],
  plasma: ['#0d0887', '#7e03a8', '#cc4778', '#f89540', '#f0f921'],
  magma: ['#000004', '#51127c', '#b73779', '#fc8961', '#fcfdbf'],
  inferno: ['#000004', '#56106e', '#bb3754', '#f98e09', '#fcffa4'],
  cividis: ['#00224e', '#434e6c', '#7d7c78', '#bcaf6f', '#fee838'],
  YlOrRd: ['#ffffb2', '#fecc5c', '#fd8d3c', '#f03b20', '#bd0026'],
  YlGnBu: ['#ffffcc', '#a1dab4', '#41b6c4', '#2c7fb8', '#253494'],
  YlGn: ['#ffffcc', '#c2e699', '#78c679', '#31a354', '#006837'],
  Blues: ['#eff3ff', '#bdd7e7', '#6baed6', '#3182bd', '#08519c'],
  Greens: ['#edf8e9', '#bae4b3', '#74c476', '#31a354', '#006d2c'],
  Reds: ['#fee5d9', '#fcae91', '#fb6a4a', '#de2d26', '#a50f15'],
  Oranges: ['#feedde', '#fdbe85', '#fd8d3c', '#e6550d', '#a63603'],
  Purples: ['#f2f0f7', '#cbc9e2', '#9e9ac8', '#756bb1', '#54278f'],
  Greys: ['#f7f7f7', '#cccccc', '#969696', '#636363', '#252525'],
  RdYlGn: ['#d7191c', '#fdae61', '#ffffbf', '#a6d96a', '#1a9641'],
  RdYlBu: ['#d7191c', '#fdae61', '#ffffbf', '#abd9e9', '#2c7bb6'],
  RdBu: ['#ca0020', '#f4a582', '#f7f7f7', '#92c5de', '#0571b0'],
  Spectral: ['#d7191c', '#fdae61', '#ffffbf', '#abdda4', '#2b83ba'],
  terrain: ['#333399', '#00b2b2', '#99e599', '#c6b38b', '#ffffff']
};
var ICONS = {
  zoom: '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/></svg>',
  chev: '<svg viewBox="0 0 24 24"><path d="M6 9l6 6 6-6"/></svg>',
  home: '<svg viewBox="0 0 24 24"><path d="M4 11l8-7 8 7"/><path d="M6 10v10h12V10"/></svg>',
  globe: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/></svg>',
  mountain: '<svg viewBox="0 0 24 24"><path d="M3 20l6-10 4 6 3-4 5 8z"/></svg>',
  camera: '<svg viewBox="0 0 24 24"><path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/></svg>',
  layers: '<svg viewBox="0 0 24 24"><path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/></svg>',
  popout: '<svg viewBox="0 0 24 24"><path d="M14 4h6v6"/><path d="M20 4l-9 9"/><path d="M18 14v6H4V6h6"/></svg>',
  style: '<svg viewBox="0 0 24 24"><path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1"/><circle cx="15" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="18" r="2"/></svg>'
};
// pop-out copy of this page: fills its own window and starts at the view it was opened from
var POPOUT = document.documentElement.hasAttribute('data-mv-popout');
if (POPOUT) {
  try {
    var pv = JSON.parse(decodeURIComponent(document.getElementById('mv-config').getAttribute('data-view') || ''));
    SPEC.center = pv.center; SPEC.zoom = pv.zoom; SPEC.pitch = pv.pitch; SPEC.bearing = pv.bearing;
    delete SPEC.bounds;
    if (pv.basemap) SPEC.basemap = pv.basemap;
  } catch (e) {}
}

// ---------- theme + height --------------------------------------------------
function parentIsDark() {
  try {
    var r = parent.document.documentElement;
    return r.classList.contains('dark') || r.getAttribute('data-theme') === 'dark';
  } catch (e) {
    return !!(window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches);
  }
}
function applyTheme() { document.documentElement.setAttribute('data-theme', parentIsDark() ? 'dark' : 'light'); }
applyTheme();
try {
  new MutationObserver(applyTheme).observe(parent.document.documentElement, { attributes: true, attributeFilter: ['class', 'data-theme'] });
} catch (e) {
  if (window.matchMedia) matchMedia('(prefers-color-scheme: dark)').addEventListener('change', applyTheme);
}
function reportHeight() {
  var h = document.documentElement.scrollHeight;
  try { parent.postMessage({ type: 'iframe:height', height: h }, '*'); } catch (e) {}
  // older Open WebUI builds ignore iframe:height; with same-origin on we can size the frame directly
  try { if (window.frameElement) window.frameElement.style.height = h + 'px'; } catch (e) {}
}
var wrap = document.getElementById('mv-wrap');
wrap.style.height = POPOUT ? '100vh' : CFG.height + 'px';
if (POPOUT) { wrap.style.border = '0'; wrap.style.borderRadius = '0'; }
window.addEventListener('load', reportHeight);
setTimeout(reportHeight, 50);

if (!window.maplibregl) {
  document.getElementById('mv-msg').textContent = 'Could not load MapLibre GL from ' + CFG.maplibreJs + '. Check the Map Visualizer network settings.';
  reportHeight();
  return;
}

// ---------- helpers -----------------------------------------------------------
function el(tag, attrs, kids) {
  var n = document.createElement(tag);
  if (attrs) Object.keys(attrs).forEach(function (k) {
    if (k === 'text') n.textContent = attrs[k];
    else if (k === 'html') n.innerHTML = attrs[k];
    else if (k.slice(0, 2) === 'on') n.addEventListener(k.slice(2), attrs[k]);
    else if (k === 'style') n.style.cssText = attrs[k];
    else n.setAttribute(k, attrs[k]);
  });
  (kids || []).forEach(function (c) { if (c) n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
  return n;
}
function num(v, d) { var n = parseFloat(v); return isFinite(n) ? n : d; }
function pick() { for (var i = 0; i < arguments.length; i++) if (arguments[i] !== undefined && arguments[i] !== null) return arguments[i]; }
function absUrl(u) {
  // URL#href percent-encodes {z}/{x}/{y} in paths; restore the template braces
  try { return new URL(u, CFG.base || location.href).href.replace(/%7B/gi, '{').replace(/%7D/gi, '}'); } catch (e) { return u; }
}
function withParams(url, params) {
  var parts = [];
  Object.keys(params).forEach(function (k) {
    var v = params[k];
    if (v === undefined || v === null || (v === '' && k.toLowerCase() !== 'styles')) return; // WMS needs an empty STYLES=
    parts.push(encodeURIComponent(k) + '=' + encodeURIComponent(v));
  });
  if (!parts.length) return url;
  return url + (url.indexOf('?') >= 0 ? (/[?&]$/.test(url) ? '' : '&') : '?') + parts.join('&');
}
function mergeParams(base, extra) {
  // case-insensitive override so params:{version:..} replaces VERSION
  var out = {};
  Object.keys(base).forEach(function (k) { out[k] = base[k]; });
  Object.keys(extra || {}).forEach(function (k) {
    Object.keys(out).forEach(function (o) { if (o.toLowerCase() === k.toLowerCase()) delete out[o]; });
    out[k] = extra[k];
  });
  return out;
}
function expandSub(url) {
  var m = url.match(/\{([a-z0-9])-([a-z0-9])\}/i);
  if (!m) return url.indexOf('{s}') >= 0 ? ['a', 'b', 'c'].map(function (s) { return url.replace('{s}', s); }) : [url];
  var out = [];
  for (var c = m[1].charCodeAt(0); c <= m[2].charCodeAt(0); c++) out.push(url.replace(m[0], String.fromCharCode(c)));
  return out;
}
function merc(lng, lat) {
  var x = lng * 20037508.34 / 180;
  var y = Math.log(Math.tan((90 + lat) * Math.PI / 360)) / (Math.PI / 180) * 20037508.34 / 180;
  return [x, y];
}
function extendBounds(b, c) {
  if (!isFinite(c[0]) || !isFinite(c[1])) return;
  if (c[0] < b[0]) b[0] = c[0]; if (c[1] < b[1]) b[1] = c[1];
  if (c[0] > b[2]) b[2] = c[0]; if (c[1] > b[3]) b[3] = c[1];
}
function walkCoords(coords, fn) {
  if (!coords) return;
  if (typeof coords[0] === 'number') { fn(coords); return; }
  for (var i = 0; i < coords.length; i++) walkCoords(coords[i], fn);
}
function eachGeometry(gj, fn) {
  if (!gj) return;
  if (gj.type === 'FeatureCollection') (gj.features || []).forEach(function (f) { eachGeometry(f, fn); });
  else if (gj.type === 'Feature') eachGeometry(gj.geometry, fn);
  else if (gj.type === 'GeometryCollection') (gj.geometries || []).forEach(function (g) { eachGeometry(g, fn); });
  else if (gj.coordinates) fn(gj);
}
function geojsonBounds(gj) {
  var b = [Infinity, Infinity, -Infinity, -Infinity];
  eachGeometry(gj, function (g) { walkCoords(g.coordinates, function (c) { extendBounds(b, c); }); });
  return isFinite(b[0]) ? b : null;
}
function swapXY(gj) {
  eachGeometry(gj, function (g) { walkCoords(g.coordinates, function (c) { var t = c[0]; c[0] = c[1]; c[1] = t; }); });
}
function geomKinds(gj) {
  var k = {};
  eachGeometry(gj, function (g) { k[g.type.replace('Multi', '')] = true; });
  return k;
}
function toFeatureCollection(gj) {
  if (!gj) return { type: 'FeatureCollection', features: [] };
  if (Array.isArray(gj)) return { type: 'FeatureCollection', features: gj };
  if (gj.type === 'FeatureCollection') return gj;
  if (gj.type === 'Feature') return { type: 'FeatureCollection', features: [gj] };
  if (gj.coordinates || gj.type === 'GeometryCollection') return { type: 'FeatureCollection', features: [{ type: 'Feature', properties: {}, geometry: gj }] };
  return gj;
}
function fetchJson(url) {
  var ac = window.AbortController ? new AbortController() : null;
  var tm = ac ? setTimeout(function () { ac.abort(); }, 60000) : 0; // a hung server must not block the initial fit
  return fetch(url, ac ? { signal: ac.signal } : undefined).then(function (r) {
    clearTimeout(tm);
    if (!r.ok) throw new Error('HTTP ' + r.status + ' ' + r.statusText);
    return r.text();
  }).then(function (t) {
    try { return JSON.parse(t); } catch (e) {
      var snippet = t.replace(/\s+/g, ' ').slice(0, 160);
      throw new Error('Response is not JSON: ' + snippet);
    }
  });
}
function hexToRgb(h) {
  h = h.replace('#', '');
  if (h.length === 3) h = h.split('').map(function (c) { return c + c; }).join('');
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}
function rampColors(name, n) {
  var stops = Array.isArray(name) ? name : (COLORMAPS[name] || COLORMAPS[String(name).replace(/_r$/, '')] || COLORMAPS.viridis);
  if (typeof name === 'string' && /_r$/.test(name)) stops = stops.slice().reverse();
  if (n <= 1) return [stops[stops.length - 1]];
  var out = [];
  for (var i = 0; i < n; i++) {
    var t = i / (n - 1) * (stops.length - 1), lo = Math.floor(t), hi = Math.min(lo + 1, stops.length - 1), f = t - lo;
    var a = hexToRgb(stops[lo]), b = hexToRgb(stops[hi]);
    out.push('#' + [0, 1, 2].map(function (j) { return ('0' + Math.round(a[j] + (b[j] - a[j]) * f).toString(16)).slice(-2); }).join(''));
  }
  return out;
}
function fmtNum(v) {
  if (Math.abs(v) >= 1000) return Math.round(v).toLocaleString();
  return String(Math.round(v * 100) / 100);
}

// ---------- map ---------------------------------------------------------------
var basemapIndex = {};
CFG.basemaps.forEach(function (b) { basemapIndex[b.id.toLowerCase()] = b; });
function resolveBasemap(v) {
  if (!v) v = CFG.defaultBasemap;
  if (typeof v === 'object') return { id: v.name || 'Custom', group: 'Custom', type: v.type || (v.url ? 'style' : 'raster'), tiles: v.tiles, url: v.url, attribution: v.attribution, maxzoom: v.maxzoom };
  var b = basemapIndex[String(v).toLowerCase()];
  if (b) return b;
  if (/^https?:|^\//.test(v)) {
    if (/\{z\}/.test(v)) return { id: 'Custom tiles', group: 'Custom', type: 'raster', tiles: expandSub(absUrl(v)) };
    return { id: 'Custom style', group: 'Custom', type: 'style', url: absUrl(v) };
  }
  return basemapIndex[CFG.defaultBasemap.toLowerCase()] || CFG.basemaps[0];
}
function basemapStyle(bm) {
  var style = { version: 8, glyphs: CFG.glyphs, sources: {}, layers: [{ id: 'bm-bg', type: 'background', paint: { 'background-color': '#dfe6ea' } }] };
  if (bm.type === 'raster') {
    style.sources.bm = { type: 'raster', tiles: bm.tiles, tileSize: 256, maxzoom: bm.maxzoom || 19, attribution: bm.attribution || '' };
    style.layers.push({ id: 'bm', type: 'raster', source: 'bm' });
    if (bm.overlay) {
      style.sources['bm-ov'] = { type: 'raster', tiles: bm.overlay, tileSize: 256, maxzoom: bm.maxzoom || 19 };
      style.layers.push({ id: 'bm-ov', type: 'raster', source: 'bm-ov' });
    }
  }
  return style;
}
function styleTarget(bm) { return bm.type === 'style' ? bm.url : basemapStyle(bm); }

var currentBasemap = resolveBasemap(SPEC.basemap);
var mapOpts = {
  container: 'mv-map',
  style: styleTarget(currentBasemap),
  center: SPEC.center || [0, 20],
  zoom: pick(SPEC.zoom, SPEC.center ? 10 : 1.3),
  pitch: num(SPEC.pitch, 0),
  bearing: num(SPEC.bearing, 0),
  maxPitch: 85,
  attributionControl: { compact: true },
  canvasContextAttributes: { preserveDrawingBuffer: true }
};
var map;
try {
  map = new maplibregl.Map(mapOpts);
} catch (e) {
  document.getElementById('mv-msg').textContent = 'Map failed to start: ' + e.message;
  reportHeight();
  return;
}
document.getElementById('mv-msg').remove();
map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-right');
map.addControl(new maplibregl.ScaleControl({ unit: SPEC.units === 'imperial' ? 'imperial' : 'metric' }), 'bottom-left');
try { map.addControl(new maplibregl.FullscreenControl({ container: wrap }), 'top-right'); } catch (e) {}

var pmtilesProtocol = null;
function ensurePmtiles() {
  if (pmtilesProtocol) return pmtilesProtocol;
  if (!window.pmtiles) throw new Error('PMTiles library failed to load');
  pmtilesProtocol = new pmtiles.Protocol();
  maplibregl.addProtocol('pmtiles', pmtilesProtocol.tile);
  return pmtilesProtocol;
}

// ---------- layer registry -----------------------------------------------------
// entries are kept in draw order (index 0 = bottom)
var entries = [];
var uid = 0;

function newEntry(L, i) {
  var e = {
    key: 'u-' + (++uid),
    spec: L,
    name: L.name || (L.type + ' ' + (i + 1)),
    type: L.type,
    visible: L.visible !== false,
    opacity: Math.max(0, Math.min(1, num(L.opacity, 1))),
    color: (L.style && L.style.color) || LAYER_COLORS[i % LAYER_COLORS.length],
    layerIds: [],
    sym: {},            // MapLibre layer ids by role (fill, fill-extrusion, line, outline, circle, symbol) for the style editor
    opacityProps: {},
    bounds: L.bounds || null,
    legend: null,
    legendUrl: null,
    interactive: false,
    state: 'loading',
    error: null,
    ui: null
  };
  entries.push(e);
  return e;
}
function addMl(e, def, opProps) {
  def.layout = def.layout || {};
  def.layout.visibility = e.visible ? 'visible' : 'none';
  if (e.spec.minzoom !== undefined) def.minzoom = num(e.spec.minzoom, 0);
  if (e.spec.maxzoom !== undefined) def.maxzoom = num(e.spec.maxzoom, 24);
  def.paint = def.paint || {};
  (opProps || []).forEach(function (p) {
    if (typeof def.paint[p] !== 'number') def.paint[p] = 1;
  });
  map.addLayer(def);
  e.layerIds.push(def.id);
  var role = def.type === 'line' && /-outline$/.test(def.id) ? 'outline' : def.type;
  (e.sym[role] = e.sym[role] || []).push(def.id);
  e.opacityProps[def.id] = (opProps || []).map(function (p) { return [p, def.paint[p]]; });
  applyOpacity(e, def.id);
}
function applyOpacity(e, onlyId) {
  e.layerIds.forEach(function (id) {
    if (onlyId && id !== onlyId) return;
    (e.opacityProps[id] || []).forEach(function (pp) {
      try { map.setPaintProperty(id, pp[0], pp[1] * e.opacity); } catch (err) {}
    });
  });
}
function setVisible(e, v) {
  e.visible = v;
  e.layerIds.forEach(function (id) { if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', v ? 'visible' : 'none'); });
}
function restack() {
  entries.forEach(function (e) { e.layerIds.forEach(function (id) { if (map.getLayer(id)) map.moveLayer(id); }); });
}
function fail(e, err) {
  e.state = 'error';
  e.error = (err && err.message) || String(err);
  if (window.console) console.warn('[map-visualizer]', e.name, err);
  renderPanel();
}
function done(e) { e.state = 'ready'; renderPanel(); }

// ---------- vector styling --------------------------------------------------------
function colorExpression(e, style, data) {
  var cb = style.colorBy || style.classify;
  if (!cb) return null;
  if (typeof cb === 'string') cb = { field: cb };
  var field = cb.field || cb.property || cb.column;
  if (!field) return null;
  var getter = ['get', field];
  var values = [];
  if (data) (data.features || []).forEach(function (f) { if (f.properties && f.properties[field] !== undefined && f.properties[field] !== null) values.push(f.properties[field]); });
  var numeric = values.length > 0 && values.every(function (v) { return typeof v === 'number' || (v !== '' && isFinite(Number(v))); });
  var type = cb.type || (cb.mapping || cb.categories ? 'categorical' : (cb.breaks || numeric ? 'graduated' : 'categorical'));
  var legend = [];
  var other = cb.otherColor || '#9ca3af';
  if (type === 'categorical') {
    var mapping = cb.mapping || null;
    if (!mapping) {
      var cats = cb.categories || [];
      if (!cats.length) {
        var seen = {};
        values.forEach(function (v) { if (!seen[v]) { seen[v] = 1; cats.push(v); } });
        cats.sort();
      }
      cats = cats.slice(0, 24);
      var pal = cb.colors || (cb.colormap ? rampColors(cb.colormap, cats.length) : CATEGORICAL);
      mapping = {};
      cats.forEach(function (c, i) { mapping[c] = pal[i % pal.length]; });
    }
    var keys = Object.keys(mapping);
    if (!keys.length) return null;
    var expr = ['match', ['to-string', getter]];
    keys.forEach(function (k) { expr.push(String(k), mapping[k]); legend.push({ label: String(k), color: mapping[k] }); });
    expr.push(other);
    e.legend = { title: cb.title || field, items: legend };
    return expr;
  }
  // graduated
  var breaks = cb.breaks;
  var nums = values.map(Number).filter(isFinite).sort(function (a, b) { return a - b; });
  if (!breaks) {
    var k = Math.max(2, Math.min(9, num(cb.classes || cb.k, 5)));
    if (!nums.length) return null;
    breaks = [];
    var scheme = String(cb.scheme || 'quantile').toLowerCase();
    for (var i = 1; i < k; i++) {
      if (scheme.indexOf('equal') === 0) breaks.push(nums[0] + (nums[nums.length - 1] - nums[0]) * i / k);
      else breaks.push(nums[Math.min(nums.length - 1, Math.floor(nums.length * i / k))]);
    }
    breaks = breaks.filter(function (b, j) { return j === 0 || b > breaks[j - 1]; });
  }
  var colors = cb.colors && cb.colors.length === breaks.length + 1 ? cb.colors : rampColors(cb.colors || cb.colormap || cb.cmap || 'viridis', breaks.length + 1);
  var step = ['step', ['to-number', getter, 0], colors[0]];
  breaks.forEach(function (b, j) { step.push(Number(b), colors[j + 1]); });
  var lo = nums.length ? nums[0] : null, hi = nums.length ? nums[nums.length - 1] : null;
  colors.forEach(function (c, j) {
    var a = j === 0 ? lo : breaks[j - 1], b = j === breaks.length ? hi : breaks[j];
    var label = (a === null ? '< ' + fmtNum(b) : b === null ? '≥ ' + fmtNum(a) : fmtNum(a) + ' – ' + fmtNum(b));
    legend.push({ label: label, color: c });
  });
  e.legend = { title: cb.title || field, items: legend };
  return step;
}

function addVectorLayers(e, sourceId, sourceLayer, data, color, kinds) {
  var s = e.spec.style || {};
  var base = color || e.color;
  var dynamic = colorExpression(e, s, data);
  var main = dynamic || base;
  var fillColor = s.fillColor || main;
  var stroke = s.strokeColor || (dynamic ? (s.outlineColor || '#ffffff') : base);
  var width = num(pick(s.width, s.weight, s.lineWidth), 2);
  var userFilter = s.filter || e.spec.filter;
  var pref = e.key + (sourceLayer ? '-' + sourceLayer.replace(/[^a-z0-9_]/gi, '_') : '');
  var paint = e.spec.paint || {};
  function common(def, gtypes) {
    def.source = sourceId;
    if (sourceLayer) def['source-layer'] = sourceLayer;
    var gf = ['match', ['geometry-type'], gtypes, true, false];
    def.filter = userFilter ? ['all', gf, userFilter] : gf;
    return def;
  }
  var poly = !kinds || kinds.Polygon, line = !kinds || kinds.LineString, point = !kinds || kinds.Point;
  if (poly) {
    if (s.extrude !== undefined && s.extrude !== false) {
      var h = typeof s.extrude === 'string' ? ['*', ['to-number', ['get', s.extrude], 0], num(s.extrudeScale, 1)] : num(s.extrude, 20);
      addMl(e, common({ id: pref + '-ext', type: 'fill-extrusion', paint: Object.assign({ 'fill-extrusion-color': fillColor, 'fill-extrusion-height': h, 'fill-extrusion-opacity': num(s.fillOpacity, 0.85) }, paint['fill-extrusion'] || {}) }, ['Polygon', 'MultiPolygon']), ['fill-extrusion-opacity']);
    } else {
      addMl(e, common({ id: pref + '-fill', type: 'fill', paint: Object.assign({ 'fill-color': fillColor, 'fill-opacity': num(s.fillOpacity, dynamic ? 0.75 : 0.3) }, paint.fill || {}) }, ['Polygon', 'MultiPolygon']), ['fill-opacity']);
    }
    var outline = { 'line-color': stroke, 'line-width': num(s.outlineWidth, dynamic ? 0.6 : width) };
    if (s.dash) outline['line-dasharray'] = s.dash;
    addMl(e, common({ id: pref + '-outline', type: 'line', paint: outline }, ['Polygon', 'MultiPolygon']), ['line-opacity']);
  }
  if (line) {
    var lp = Object.assign({ 'line-color': main, 'line-width': width }, paint.line || {});
    if (s.dash) lp['line-dasharray'] = s.dash;
    addMl(e, common({ id: pref + '-line', type: 'line', paint: lp, layout: { 'line-cap': 'round', 'line-join': 'round' } }, ['LineString', 'MultiLineString']), ['line-opacity']);
  }
  if (point) {
    addMl(e, common({ id: pref + '-pt', type: 'circle', paint: Object.assign({
      'circle-color': main, 'circle-radius': num(s.radius, 6), 'circle-opacity': num(s.pointOpacity, 0.9),
      'circle-stroke-color': s.strokeColor || '#ffffff', 'circle-stroke-width': num(s.strokeWidth, 1.5)
    }, paint.circle || {}) }, ['Point', 'MultiPoint']), ['circle-opacity', 'circle-stroke-opacity']);
  }
  if (s.label) {
    var dark = (s.labelColor || '#111827');
    addMl(e, common({
      id: pref + '-label', type: 'symbol',
      layout: {
        'text-field': ['to-string', ['get', s.label]], 'text-font': [CFG.font], 'text-size': num(s.labelSize, 12),
        'text-offset': point && !poly && !line ? [0, 1.1] : [0, 0], 'text-anchor': point && !poly && !line ? 'top' : 'center',
        'text-max-width': 10, 'symbol-placement': line && !poly && !point ? 'line' : 'point'
      },
      paint: { 'text-color': dark, 'text-halo-color': s.labelHalo || '#ffffff', 'text-halo-width': 1.4 }
    }, ['Point', 'MultiPoint', 'LineString', 'MultiLineString', 'Polygon', 'MultiPolygon']), ['text-opacity']);
  }
  e.interactive = e.spec.popup !== false;
  if (!dynamic && !e.legend) e.swatch = base;
}

// ---------- layer loaders ---------------------------------------------------------
function addRaster(e, tiles, extra) {
  var L = e.spec;
  var src = Object.assign({ type: 'raster', tiles: tiles, tileSize: num(L.tileSize, 256), attribution: L.attribution || '' }, extra || {});
  if (L.scheme === 'tms' || L.type === 'tms') src.scheme = 'tms';
  if (L.sourceMaxzoom !== undefined) src.maxzoom = num(L.sourceMaxzoom, 22);
  if (L.bounds) src.bounds = L.bounds;
  map.addSource(e.key, src);
  var paint = Object.assign({}, L.paint || {});
  addMl(e, { id: e.key, type: 'raster', source: e.key, paint: paint }, ['raster-opacity']);
  e.swatch = 'raster';
}

var loaders = {
  xyz: function (e) {
    var L = e.spec;
    var tiles = L.tiles || expandSub(absUrl(L.url));
    addRaster(e, tiles);
  },
  wms: function (e) {
    var L = e.spec, v = L.version || '1.3.0', ts = num(L.tileSize, 256);
    var p = { SERVICE: 'WMS', REQUEST: 'GetMap', VERSION: v, LAYERS: L.layers || L.layer || '', STYLES: L.styles || '',
      FORMAT: L.format || 'image/png', TRANSPARENT: L.transparent === false ? 'FALSE' : 'TRUE', WIDTH: ts, HEIGHT: ts };
    p[v === '1.3.0' ? 'CRS' : 'SRS'] = 'EPSG:3857';
    var url = withParams(absUrl(L.url), mergeParams(p, L.params)) + '&BBOX={bbox-epsg-3857}';
    addRaster(e, [url]);
    e.wms = { url: absUrl(L.url), version: v, layers: p.LAYERS, params: L.params || {} };
    e.queryable = L.queryable !== false;
    if (L.legend !== false) {
      e.legendUrl = L.legendUrl || withParams(absUrl(L.url), mergeParams({ SERVICE: 'WMS', REQUEST: 'GetLegendGraphic', VERSION: v, FORMAT: 'image/png',
        LAYER: String(p.LAYERS).split(',')[0], STYLE: String(L.styles || '').split(',')[0], SLD_VERSION: '1.1.0' }, L.legendParams));
    }
  },
  wmts: function (e) {
    var L = e.spec, url = absUrl(L.url);
    if (/\{(TileMatrix|z)\}/i.test(url)) {
      url = url.replace(/\{TileMatrix\}/gi, (L.matrixPrefix || '') + '{z}').replace(/\{TileRow\}/gi, '{y}').replace(/\{TileCol\}/gi, '{x}')
        .replace(/\{Style\}/gi, L.style_name || L.styleName || 'default').replace(/\{TileMatrixSet\}/gi, L.tileMatrixSet || 'GoogleMapsCompatible')
        .replace(/\{Time\}/gi, L.time || 'default');
      Object.keys(L.dimensions || {}).forEach(function (k) { url = url.split('{' + k + '}').join(encodeURIComponent(L.dimensions[k])); });
    } else {
      url = withParams(url, mergeParams({ SERVICE: 'WMTS', REQUEST: 'GetTile', VERSION: '1.0.0', LAYER: L.layer || L.layers,
        STYLE: L.styleName || L.style_name || 'default', TILEMATRIXSET: L.tileMatrixSet || 'GoogleMapsCompatible', FORMAT: L.format || 'image/png' }, L.params));
      url += '&TILEMATRIX=' + encodeURIComponent(L.matrixPrefix || '') + '{z}&TILEROW={y}&TILECOL={x}';
    }
    // GIBS-style matrix sets (..._Level9) end at a fixed zoom; deeper tiles 400
    var lv = String(L.tileMatrixSet || '').match(/Level(\d+)$/i);
    addRaster(e, [url], lv && L.sourceMaxzoom === undefined ? { maxzoom: +lv[1] } : null);
  },
  cog: function (e) {
    var L = e.spec, ep = (L.titiler || CFG.titiler).replace(/\/$/, '');
    var q = { url: absUrl(L.url) };
    ['rescale', 'colormap_name', 'nodata', 'expression', 'resampling', 'return_mask', 'algorithm'].forEach(function (k) { if (L[k] !== undefined) q[k] = L[k]; });
    if (L.colormap && !q.colormap_name) q.colormap_name = String(L.colormap).toLowerCase();
    // no "@1x": newer TiTiler rejects it (422); WGS84 bounds and zoom range come from tilejson
    var url = withParams(ep + '/cog/tiles/WebMercatorQuad/{z}/{x}/{y}.png', q);
    if (L.bidx) [].concat(L.bidx).forEach(function (b) { url += '&bidx=' + encodeURIComponent(b); });
    url = url.replace(/%7B/g, '{').replace(/%7D/g, '}');
    return fetchJson(withParams(ep + '/cog/WebMercatorQuad/tilejson.json', { url: absUrl(L.url) })).catch(function () { return null; }).then(function (tj) {
      var extra = {};
      if (tj && tj.bounds && !e.bounds) e.bounds = tj.bounds;
      if (tj && isFinite(tj.minzoom) && L.minzoom === undefined) extra.minzoom = Math.max(0, tj.minzoom - 1);
      if (tj && isFinite(tj.maxzoom)) extra.maxzoom = tj.maxzoom;
      addRaster(e, [url], extra);
    });
  },
  image: function (e) {
    var L = e.spec;
    var c = L.coordinates;
    if (!c && L.bounds) c = [[L.bounds[0], L.bounds[3]], [L.bounds[2], L.bounds[3]], [L.bounds[2], L.bounds[1]], [L.bounds[0], L.bounds[1]]];
    if (!c) throw new Error('image layers need "coordinates" (4 corners TL,TR,BR,BL) or "bounds" [w,s,e,n]');
    map.addSource(e.key, { type: 'image', url: absUrl(L.url), coordinates: c });
    addMl(e, { id: e.key, type: 'raster', source: e.key, paint: {} }, ['raster-opacity']);
    if (!e.bounds) { var b = [Infinity, Infinity, -Infinity, -Infinity]; c.forEach(function (p) { extendBounds(b, p); }); e.bounds = b; }
    e.swatch = 'raster';
  },
  geojson: function (e) {
    var L = e.spec;
    var p = L.data !== undefined && L.data !== null
      ? Promise.resolve(typeof L.data === 'string' ? JSON.parse(L.data) : L.data)
      : fetchJson(absUrl(L.url));
    return p.then(function (gj) { addGeojson(e, toFeatureCollection(gj)); });
  },
  wfs: function (e) {
    var L = e.spec;
    if (L.strategy === 'bbox') return loadByViewport(e, wfsUrl);
    return fetchJson(wfsUrl(e, null)).then(function (gj) { addGeojson(e, fixAxis(e, gj)); });
  },
  ogcapi: function (e) {
    if (e.spec.strategy === 'bbox') return loadByViewport(e, ogcUrl);
    return fetchJson(ogcUrl(e, null)).then(function (gj) { addGeojson(e, gj); });
  },
  vectortiles: function (e) {
    var L = e.spec, url = absUrl(L.url || (L.tiles && L.tiles[0]) || '');
    var src = { type: 'vector', attribution: L.attribution || '' };
    if (L.tiles || /\{z\}/.test(url)) {
      src.tiles = L.tiles || expandSub(url);
      if (L.sourceMaxzoom !== undefined) src.maxzoom = num(L.sourceMaxzoom, 14);
      if (L.bounds) src.bounds = L.bounds;
    } else src.url = url;
    var layersP = L.sourceLayer || L.sourceLayers
      ? Promise.resolve([].concat(L.sourceLayer || L.sourceLayers))
      : (src.url ? fetchJson(src.url).then(function (tj) {
          if (!e.bounds && tj.bounds) e.bounds = tj.bounds;
          return (tj.vector_layers || []).map(function (v) { return v.id; });
        }) : Promise.reject(new Error('vectortiles with an {z}/{x}/{y} template need "sourceLayer"')));
    return layersP.then(function (names) {
      map.addSource(e.key, src);
      addSourceLayers(e, names);
    });
  },
  pmtiles: function (e) {
    var L = e.spec, proto = ensurePmtiles(), url = absUrl(L.url);
    var archive = new pmtiles.PMTiles(url);
    proto.add(archive);
    return archive.getHeader().then(function (h) {
      if (!e.bounds && isFinite(h.minLon) && (h.maxLon - h.minLon) < 359) e.bounds = [h.minLon, h.minLat, h.maxLon, h.maxLat];
      if (h.tileType === 1) {
        return archive.getMetadata().then(function (md) {
          var names = L.sourceLayer || L.sourceLayers ? [].concat(L.sourceLayer || L.sourceLayers) : ((md && md.vector_layers) || []).map(function (v) { return v.id; });
          map.addSource(e.key, { type: 'vector', url: 'pmtiles://' + url, attribution: L.attribution || '' });
          addSourceLayers(e, names);
        });
      }
      map.addSource(e.key, { type: 'raster', url: 'pmtiles://' + url, tileSize: num(L.tileSize, 256), attribution: L.attribution || '' });
      addMl(e, { id: e.key, type: 'raster', source: e.key, paint: {} }, ['raster-opacity']);
      e.swatch = 'raster';
    });
  },
  buildings: function (e) {
    // open building footprints: OpenStreetMap via OpenFreeMap, or Overture Maps (latest release via STAC)
    var L = e.spec, s = L.style || {}, overture = String(L.source || '').toLowerCase() === 'overture';
    var flat = String(L.mode || '').toLowerCase() === '2d';
    var srcP;
    if (overture) {
      var proto = ensurePmtiles();
      var relP = L.release ? Promise.resolve(L.release) : fetchJson(CFG.overtureCatalog).then(function (c) {
        if (!c.latest) throw new Error('Overture catalog has no "latest" release');
        return c.latest;
      });
      srcP = relP.then(function (rel) {
        var url = L.url || CFG.overtureBuildings.replace('{release}', rel);
        proto.add(new pmtiles.PMTiles(url));
        e.release = rel;
        return { type: 'vector', url: 'pmtiles://' + url };
      });
    } else {
      srcP = Promise.resolve({ type: 'vector', url: L.url || CFG.buildingsTiles });
    }
    return srcP.then(function (src) {
      map.addSource(e.key, src);
      var hgt = overture
        ? ['coalesce', ['get', 'height'], ['*', ['get', 'num_floors'], 3], 8]
        : ['coalesce', ['get', 'render_height'], ['get', 'height'], 8];
      var base = overture ? ['coalesce', ['get', 'min_height'], 0] : ['coalesce', ['get', 'render_min_height'], ['get', 'min_height'], 0];
      var color = (s.colorBy ? colorExpression(e, s, null) : null) || s.color ||
        (flat ? '#b9a48c' : ['interpolate', ['linear'], hgt, 0, '#d8d4cc', 50, '#b8b0a2', 150, '#8f8576']);
      var common = { source: e.key, 'source-layer': L.sourceLayer || 'building', minzoom: num(L.minzoom, 13) };
      if (flat) {
        addMl(e, Object.assign({ id: e.key + '-fill', type: 'fill', paint: { 'fill-color': color, 'fill-opacity': num(s.fillOpacity, 0.55) } }, common), ['fill-opacity']);
        addMl(e, Object.assign({ id: e.key + '-outline', type: 'line', paint: { 'line-color': s.strokeColor || '#7a6650', 'line-width': num(s.width, 0.6) } }, common), ['line-opacity']);
      } else {
        addMl(e, Object.assign({ id: e.key, type: 'fill-extrusion', paint: {
          'fill-extrusion-color': color, 'fill-extrusion-height': hgt, 'fill-extrusion-base': base,
          'fill-extrusion-opacity': num(s.fillOpacity, 0.9)
        } }, common), ['fill-extrusion-opacity']);
        if (!SPEC.pitch && !L._pitched) { L._pitched = true; map.once('idle', function () { if (map.getPitch() < 30) map.easeTo({ pitch: 55 }); }); }
      }
      e.swatch = typeof color === 'string' ? color : '#b8b0a2';
      e.interactive = L.popup !== false;
      if (map.getZoom() < common.minzoom) {
        e.note = 'Zoom in past level ' + common.minzoom + ' to see buildings';
        map.on('zoomend', function chk() {
          if (map.getZoom() < common.minzoom) return;
          e.note = null; map.off('zoomend', chk); renderPanel();
        });
      }
    });
  }
};

function addSourceLayers(e, names) {
  if (!names.length) throw new Error('No source layers found; set "sourceLayer"');
  var perLayerColors = names.length > 1 && !(e.spec.style && e.spec.style.color);
  if (perLayerColors) e.legend = { title: 'Source layers', items: [] };
  names.forEach(function (n, i) {
    var c = perLayerColors ? CATEGORICAL[i % CATEGORICAL.length] : null;
    addVectorLayers(e, e.key, n, null, c, null);
    if (perLayerColors) e.legend.items.push({ label: n, color: c });
  });
}

function addGeojson(e, gj) {
  if (!gj || !gj.type) throw new Error('Not valid GeoJSON');
  if (!e.bounds) e.bounds = geojsonBounds(gj);
  var count = (gj.features || []).length;
  e.featureCount = count;
  if (map.getSource(e.key)) { map.getSource(e.key).setData(gj); return; }
  map.addSource(e.key, { type: 'geojson', data: gj, attribution: e.spec.attribution || '' });
  var kinds = geomKinds(gj);
  if (!Object.keys(kinds).length) kinds = null;
  addVectorLayers(e, e.key, null, gj, null, kinds);
}

function fixAxis(e, gj) {
  var order = e.spec.axisOrder || 'auto';
  if (order === 'lonlat') return gj;
  var swap = order === 'latlon';
  if (order === 'auto') {
    var bigX = false, bigY = false;
    eachGeometry(gj, function (g) { walkCoords(g.coordinates, function (c) { if (Math.abs(c[0]) > 90) bigX = true; if (Math.abs(c[1]) > 90) bigY = true; }); });
    if (bigX) swap = false;
    else if (bigY) swap = true;
    else {
      var crs = gj.crs && gj.crs.properties && gj.crs.properties.name || '';
      swap = /EPSG::4326$/.test(crs);
    }
  }
  if (swap) swapXY(gj);
  return gj;
}
function wfsUrl(e, bbox) {
  var L = e.spec, v = L.version || '2.0.0', two = v.charAt(0) === '2';
  var p = { SERVICE: 'WFS', REQUEST: 'GetFeature', VERSION: v, OUTPUTFORMAT: L.outputFormat || 'application/json', SRSNAME: L.srsName || 'EPSG:4326' };
  p[two ? 'TYPENAMES' : 'TYPENAME'] = L.typeName || L.typeNames || L.layers || L.layer;
  var max = num(L.maxFeatures, 2000);
  if (max > 0) p[two ? 'COUNT' : 'MAXFEATURES'] = max;
  if (L.cqlFilter) p.CQL_FILTER = L.cqlFilter;
  if (bbox && !L.cqlFilter) p.BBOX = v === '1.0.0' ? bbox.join(',') : [bbox[1], bbox[0], bbox[3], bbox[2]].join(',') + ',urn:ogc:def:crs:EPSG::4326';
  return withParams(absUrl(L.url), mergeParams(p, L.params));
}
function ogcUrl(e, bbox) {
  var L = e.spec, u = absUrl(L.url).replace(/\/$/, '');
  var parts = u.split('?');
  if (!/\/items$/.test(parts[0])) parts[0] = parts[0] + (L.collection ? '/collections/' + encodeURIComponent(L.collection) : '') + '/items';
  u = parts.join('?');
  var p = mergeParams({ f: 'json', limit: num(L.limit || L.maxFeatures, 1000) }, L.params);
  if (bbox) p.bbox = bbox.map(function (n) { return n.toFixed(6); }).join(',');
  return withParams(u, p);
}
function loadByViewport(e, urlFn) {
  var minz = num(e.spec.loadMinzoom, 10), timer = 0, seq = 0;
  function load() {
    if (!e.visible) return Promise.resolve();
    if (map.getZoom() < minz) { e.note = 'Zoom in past level ' + minz + ' to load features'; renderPanel(); return Promise.resolve(); }
    var b = map.getBounds(), bbox = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()], my = ++seq;
    e.state = 'loading'; e.note = null; renderPanel();
    return fetchJson(urlFn(e, bbox)).then(function (gj) {
      if (my !== seq) return;
      if (urlFn === wfsUrl) fixAxis(e, gj);
      var keepBounds = e.bounds;
      addGeojson(e, gj);
      e.bounds = keepBounds;
      restack(); done(e);
    }).catch(function (err) { fail(e, err); });
  }
  map.on('moveend', function () { clearTimeout(timer); timer = setTimeout(load, 350); });
  e.reload = load;
  e.bounds = e.bounds || null;
  e.noFit = true;
  return load();
}

// ---------- popups / identify ---------------------------------------------------------
var popup = new maplibregl.Popup({ maxWidth: '320px', closeButton: true });
function propsTable(props, fields) {
  var t = el('table');
  var keys = fields && fields.length ? fields : Object.keys(props || {});
  keys.slice(0, 40).forEach(function (k) {
    var v = props[k];
    if (v === undefined || v === null || typeof v === 'object') { if (v && typeof v === 'object') v = JSON.stringify(v); else return; }
    var s = String(v);
    var td = el('td');
    if (/^https?:\/\//.test(s)) td.appendChild(el('a', { href: s, target: '_blank', rel: 'noopener', text: s.length > 40 ? s.slice(0, 40) + '…' : s }));
    else td.textContent = s;
    t.appendChild(el('tr', null, [el('td', { text: k }), td]));
  });
  return t;
}
function entryForLayerId(id) {
  for (var i = 0; i < entries.length; i++) if (entries[i].layerIds.indexOf(id) >= 0) return entries[i];
}
map.on('click', function (ev) {
  var ids = [];
  entries.forEach(function (e) { if (e.visible && e.interactive) ids = ids.concat(e.layerIds.filter(function (id) { return map.getLayer(id); })); });
  var feats = ids.length ? map.queryRenderedFeatures(ev.point, { layers: ids }) : [];
  var box = el('div', { 'class': 'mv-pop' });
  var shown = 0, seenEntry = {};
  feats.forEach(function (f) {
    var e = entryForLayerId(f.layer.id);
    if (!e || shown >= 5) return;
    var sig = e.key + JSON.stringify(f.properties);
    if (seenEntry[sig]) return; seenEntry[sig] = 1;
    shown++;
    box.appendChild(el('h4', { text: e.name + (f.sourceLayer && e.type !== 'geojson' ? ' › ' + f.sourceLayer : '') }));
    var fields = Array.isArray(e.spec.popup) ? e.spec.popup : null;
    box.appendChild(propsTable(f.properties, fields));
  });
  var wmsHits = entries.filter(function (e) { return e.wms && e.queryable && e.visible; }).reverse();
  if (!shown && !wmsHits.length) return;
  if (shown) popup.setLngLat(ev.lngLat).setDOMContent(box).addTo(map);
  if (!wmsHits.length) return;
  var b = map.getBounds(), sw = merc(b.getWest(), b.getSouth()), ne = merc(b.getEast(), b.getNorth());
  var cv = map.getCanvas(), W = cv.clientWidth, H = cv.clientHeight;
  Promise.all(wmsHits.map(function (e) {
    var w = e.wms, fmt = e.spec.infoFormat || 'application/json';
    var p = { SERVICE: 'WMS', REQUEST: 'GetFeatureInfo', VERSION: w.version, LAYERS: w.layers, QUERY_LAYERS: e.spec.queryLayers || w.layers,
      STYLES: e.spec.styles || '', INFO_FORMAT: fmt, FEATURE_COUNT: 5, WIDTH: W, HEIGHT: H, BBOX: [sw[0], sw[1], ne[0], ne[1]].join(',') };
    p[w.version === '1.3.0' ? 'CRS' : 'SRS'] = 'EPSG:3857';
    p[w.version === '1.3.0' ? 'I' : 'X'] = Math.round(ev.point.x);
    p[w.version === '1.3.0' ? 'J' : 'Y'] = Math.round(ev.point.y);
    return fetch(withParams(w.url, mergeParams(p, w.params))).then(function (r) { return r.text(); }).then(function (txt) {
      var gj = null;
      try { gj = JSON.parse(txt); } catch (err) {}
      if (gj && gj.features) {
        if (!gj.features.length) return 0;
        box.appendChild(el('h4', { text: e.name }));
        gj.features.slice(0, 5).forEach(function (f) { box.appendChild(propsTable(f.properties || {}, Array.isArray(e.spec.popup) ? e.spec.popup : null)); });
        return 1;
      }
      var plain = txt.replace(/\s+/g, ' ').trim();
      if (!plain || /ServiceException|no features|^\s*$/i.test(plain) || /<body[^>]*>\s*<\/body>/i.test(txt)) return 0;
      box.appendChild(el('h4', { text: e.name }));
      if (/<html|<table/i.test(txt)) { var fr = el('iframe', { sandbox: '' }); fr.srcdoc = txt; box.appendChild(fr); }
      else box.appendChild(el('div', { text: plain.slice(0, 600) }));
      return 1;
    }).catch(function () { return 0; });
  })).then(function (hits) {
    if (hits.reduce(function (a, b) { return a + b; }, 0) > 0) popup.setLngLat(ev.lngLat).setDOMContent(box).addTo(map);
  });
});
map.on('mousemove', function (ev) {
  var ids = [];
  entries.forEach(function (e) { if (e.visible && e.interactive) ids = ids.concat(e.layerIds.filter(function (id) { return map.getLayer(id); })); });
  var hit = ids.length && map.queryRenderedFeatures(ev.point, { layers: ids }).length;
  map.getCanvas().style.cursor = hit ? 'pointer' : '';
  coords.textContent = ev.lngLat.lat.toFixed(5) + ', ' + ev.lngLat.lng.toFixed(5) + '  z' + map.getZoom().toFixed(1);
});

// ---------- UI: panel ---------------------------------------------------------------
var panel = el('div', { id: 'mv-panel', 'class': 'mv-card' });
var coords = el('div', { id: 'mv-coords', 'class': 'mv-card' });
wrap.appendChild(panel);
wrap.appendChild(coords);
var collapsed = CFG.height < 360 || wrap.clientWidth < 480 || SPEC.panel === 'collapsed' || SPEC.panel === false;
var openDetails = {};
var bmOpen = false;

function thumbStyle(bm) {
  if (bm.type === 'raster' && bm.tiles) {
    var t = (bm.thumbTile || '4/8/5').split('/');  // z/x/y sample tile; regional basemaps set their own
    var u = bm.tiles[0].replace('{z}', t[0]).replace('{x}', t[1]).replace('{y}', t[2]);
    return 'background-image:url("' + u.replace(/"/g, '%22') + '")';
  }
  if (bm.thumb) return 'background:' + bm.thumb;
  return 'background:linear-gradient(135deg,#e5e7eb,#cbd5e1)';
}
function setBasemap(bm) {
  currentBasemap = bm;
  map.setStyle(styleTarget(bm), {
    diff: false,
    transformStyle: function (prev, next) {
      if (!prev) return next;
      var out = Object.assign({}, next);
      out.sources = Object.assign({}, next.sources);
      Object.keys(prev.sources).forEach(function (k) { if (k.indexOf('u-') === 0 || k === 'mv-dem') out.sources[k] = prev.sources[k]; });
      out.layers = next.layers.concat(prev.layers.filter(function (l) { return l.id.indexOf('u-') === 0; }));
      if (!out.glyphs) out.glyphs = CFG.glyphs;
      if (prev.terrain) out.terrain = prev.terrain;
      if (prev.projection) out.projection = prev.projection;
      return out;
    }
  });
  renderPanel();
}
// symbology editor (vector layers): colour, outline colour, line width, point size
function styleControls(e, det) {
  var S = e.sym;
  function first(roles) { for (var i = 0; i < roles.length; i++) if (S[roles[i]]) return S[roles[i]][0]; }
  function cur(id, prop, fb) {
    var v = id ? map.getPaintProperty(id, prop) : null;
    if (typeof v === 'string' && /^#[0-9a-f]{6}$/i.test(v)) return v;
    return typeof v === 'number' ? v : fb;
  }
  function apply(pairs, v) {
    pairs.forEach(function (p) { (S[p[0]] || []).forEach(function (id) { try { map.setPaintProperty(id, p[1], v); } catch (err) {} }); });
  }
  function row(label, input) { det.appendChild(el('div', { 'class': 'mv-legend-item mv-sym' }, [el('span', { text: label }), input])); }
  var fillish = first(['fill', 'fill-extrusion', 'line', 'circle']);
  if (fillish) {
    var mainProp = S.fill ? 'fill-color' : S['fill-extrusion'] ? 'fill-extrusion-color' : S.line ? 'line-color' : 'circle-color';
    var c = el('input', { type: 'color', title: 'Colour (replaces any colour-by-attribute scheme)',
      value: cur(fillish, mainProp, typeof e.swatch === 'string' && e.swatch.charAt(0) === '#' ? e.swatch : e.color) });
    c.addEventListener('input', function () {
      apply([['fill', 'fill-color'], ['fill-extrusion', 'fill-extrusion-color'], ['line', 'line-color'], ['circle', 'circle-color']], c.value);
      e.swatch = c.value; e.legend = null;
    });
    c.addEventListener('change', renderPanel);
    row('Colour', c);
  }
  var edge = first(['outline', 'circle']);
  if (edge) {
    var o = el('input', { type: 'color', title: 'Outline colour', value: cur(edge, S.outline ? 'line-color' : 'circle-stroke-color', '#ffffff') });
    o.addEventListener('input', function () { apply([['outline', 'line-color'], ['circle', 'circle-stroke-color']], o.value); });
    row('Outline', o);
  }
  var lineish = first(['line', 'outline']);
  if (lineish) {
    var w = el('input', { type: 'range', min: '0', max: '12', step: '0.5', title: 'Line width', value: String(cur(lineish, 'line-width', 1)) });
    w.addEventListener('input', function () { apply([['line', 'line-width'], ['outline', 'line-width']], +w.value); });
    row('Width', w);
  }
  if (S.circle) {
    var r = el('input', { type: 'range', min: '1', max: '24', step: '1', title: 'Point size', value: String(cur(S.circle[0], 'circle-radius', 6)) });
    r.addEventListener('input', function () { apply([['circle', 'circle-radius']], +r.value); });
    row('Size', r);
  }
}
function renderPanel() {
  panel.innerHTML = '';
  panel.className = 'mv-card' + (collapsed ? ' collapsed' : '');
  var head = el('div', { 'class': 'mv-head', onclick: function () { collapsed = !collapsed; renderPanel(); } }, [
    el('span', { html: ICONS.layers, 'class': 'mv-btn', style: 'padding:0' }),
    el('span', { 'class': 'mv-title', text: SPEC.title || 'Map' }),
    el('span', { 'class': 'mv-btn', html: ICONS.chev, style: collapsed ? 'transform:rotate(-90deg)' : '' })
  ]);
  panel.appendChild(head);
  var body = el('div', { 'class': 'mv-body' });
  panel.appendChild(body);

  // overlays (top of draw order first, like a GIS table of contents)
  if (entries.length) {
    var sec = el('div', { 'class': 'mv-sec' }, [el('div', { 'class': 'mv-label', text: 'Layers' })]);
    entries.slice().reverse().forEach(function (e) {
      var sw;
      if (e.state === 'loading') sw = el('span', { 'class': 'mv-spin' });
      else if (e.swatch === 'raster') sw = el('span', { 'class': 'mv-sw raster' });
      else sw = el('span', { 'class': 'mv-sw', style: 'background:' + (e.swatch || (e.legend ? 'conic-gradient(' + e.legend.items.slice(0, 6).map(function (i) { return i.color; }).join(',') + ')' : e.color)) });
      var cb = el('input', { type: 'checkbox', title: 'Show / hide', onchange: function () { setVisible(e, cb.checked); if (cb.checked && e.reload) e.reload(); } });
      cb.checked = e.visible;
      var zoomBtn = el('button', { 'class': 'mv-btn', title: 'Zoom to layer', html: ICONS.zoom, onclick: function () { zoomTo(e); } });
      if (!e.bounds) zoomBtn.style.visibility = 'hidden';
      function toggle() { openDetails[e.key] = !openDetails[e.key]; renderPanel(); }
      var nameEl = el('span', { 'class': 'mv-name', text: e.name, title: e.name + ' (' + e.type + ') – click for opacity and style', onclick: toggle });
      var styleBtn = el('button', { 'class': 'mv-btn' + (openDetails[e.key] ? ' on' : ''), title: 'Opacity and style', html: ICONS.style, onclick: toggle });
      sec.appendChild(el('div', { 'class': 'mv-row' }, [cb, sw, nameEl, styleBtn, zoomBtn]));
      if (e.error) sec.appendChild(el('div', { 'class': 'mv-err', text: e.error }));
      else if (e.note) sec.appendChild(el('div', { 'class': 'mv-err', style: 'color:var(--mv-muted)', text: e.note }));
      var det = el('div', { 'class': 'mv-detail' + (openDetails[e.key] || e.legend || e.legendUrl ? ' open' : '') });
      if (openDetails[e.key]) {
        var rng = el('input', { type: 'range', min: '0', max: '100', value: String(Math.round(e.opacity * 100)), title: 'Opacity',
          oninput: function () { e.opacity = rng.value / 100; applyOpacity(e); } });
        det.appendChild(el('div', { 'class': 'mv-legend-item' }, ['Opacity', rng]));
        styleControls(e, det);
        if (e.featureCount !== undefined) det.appendChild(el('div', { 'class': 'mv-legend-item', text: e.featureCount + ' features' }));
      }
      if (e.legend) {
        var lg = el('div', { 'class': 'mv-legend' });
        if (e.legend.title) lg.appendChild(el('div', { 'class': 'mv-legend-item', style: 'font-weight:600', text: e.legend.title }));
        e.legend.items.forEach(function (it) { lg.appendChild(el('div', { 'class': 'mv-legend-item' }, [el('span', { 'class': 'mv-sw', style: 'background:' + it.color }), it.label])); });
        det.appendChild(lg);
      }
      if (e.legendUrl) {
        var img = el('img', { src: e.legendUrl, alt: '', onerror: function () { img.remove(); }, onload: reportHeight });
        det.appendChild(el('div', { 'class': 'mv-legend' }, [img]));
      }
      if (det.childNodes.length) sec.appendChild(det);
    });
    body.appendChild(sec);
  }

  // basemap gallery
  var bsec = el('div', { 'class': 'mv-sec' }, [el('div', { 'class': 'mv-label', text: 'Basemap' })]);
  var cur = el('button', { 'class': 'mv-bm-current', onclick: function () { bmOpen = !bmOpen; renderPanel(); } }, [
    el('span', { 'class': 'mv-thumb', style: thumbStyle(currentBasemap) }),
    el('span', { 'class': 'mv-name', text: currentBasemap.id }),
    el('span', { 'class': 'mv-btn', html: ICONS.chev, style: bmOpen ? 'transform:rotate(180deg)' : '' })
  ]);
  bsec.appendChild(cur);
  var grid = el('div', { 'class': 'mv-bm-grid' + (bmOpen ? ' open' : '') });
  if (bmOpen) {
    var lastGroup = null;
    CFG.basemaps.forEach(function (bm) {
      if (bm.group !== lastGroup) { lastGroup = bm.group; grid.appendChild(el('div', { 'class': 'mv-bm-group', text: bm.group })); }
      grid.appendChild(el('button', { 'class': 'mv-bm-opt' + (bm.id === currentBasemap.id ? ' active' : ''), title: bm.id,
        onclick: function () { bmOpen = false; setBasemap(bm); } }, [
        el('span', { 'class': 'mv-thumb', style: thumbStyle(bm) }),
        el('span', { text: bm.id.replace(/^(OpenFreeMap|Esri|NASAGIBS|USGS|PDOK|OpenStreetMap)\./, '') })
      ]));
    });
  }
  bsec.appendChild(grid);
  body.appendChild(bsec);
  requestAnimationFrame(reportHeight);
}

// ---------- UI: toolbar ---------------------------------------------------------------
var tools = el('div', { id: 'mv-tools', 'class': 'mv-card' });
wrap.appendChild(tools);
var globeOn = !!SPEC.globe, terrainOn = false;
function toolBtn(icon, title, fn) { var b = el('button', { 'class': 'mv-btn', title: title, html: icon, onclick: function () { fn(b); } }); tools.appendChild(b); return b; }
toolBtn(ICONS.home, 'Reset view', function () { fitInitial(true); });
var globeBtn = toolBtn(ICONS.globe, 'Globe projection', function (b) { globeOn = !globeOn; setGlobe(); b.classList.toggle('on', globeOn); });
var terrainBtn = toolBtn(ICONS.mountain, '3D terrain', function (b) { setTerrain(!terrainOn); b.classList.toggle('on', terrainOn); });
toolBtn(ICONS.camera, 'Save as PNG', function () { exportPng(); });
if (!POPOUT && window.mvPageHtml) toolBtn(ICONS.popout, 'Open in a new window', function () { popOut(); });
globeBtn.classList.toggle('on', globeOn);

function popOut() {
  var c = map.getCenter();
  var view = { center: [c.lng, c.lat], zoom: map.getZoom(), pitch: map.getPitch(), bearing: map.getBearing(),
    basemap: basemapIndex[String(currentBasemap.id).toLowerCase()] ? currentBasemap.id : null };
  var html = window.mvPageHtml.replace('<html ', '<html data-mv-popout="1" ')
    .replace('id="mv-config">', 'id="mv-config" data-view="' + encodeURIComponent(JSON.stringify(view)) + '">');
  var url = URL.createObjectURL(new Blob([html], { type: 'text/html' }));
  var w = null;
  try { w = window.open(url, '_blank'); } catch (err) {}
  if (!w) {
    // popups blocked: hand the standalone page over as a file instead
    var a = el('a', { href: url, download: (SPEC.title || 'map').replace(/[^a-z0-9-_ ]/gi, '') + '.html' });
    document.body.appendChild(a); a.click(); a.remove();
  }
}

function setGlobe() { try { map.setProjection({ type: globeOn ? 'globe' : 'mercator' }); } catch (e) {} }
function setTerrain(on) {
  terrainOn = on;
  terrainBtn.classList.toggle('on', on);
  if (on) {
    if (!map.getSource('mv-dem')) map.addSource('mv-dem', { type: 'raster-dem', tiles: [CFG.terrainTiles], encoding: 'terrarium', tileSize: 256, maxzoom: 15 });
    map.setTerrain({ source: 'mv-dem', exaggeration: num(SPEC.terrainExaggeration || (typeof SPEC.terrain === 'number' ? SPEC.terrain : 1.3), 1.3) });
    if (map.getPitch() < 20) map.easeTo({ pitch: 60 });
  } else {
    map.setTerrain(null);
  }
}
function exportPng() {
  map.once('render', function () {
    try {
      var a = el('a', { href: map.getCanvas().toDataURL('image/png'), download: (SPEC.title || 'map').replace(/[^a-z0-9-_ ]/gi, '') + '.png' });
      document.body.appendChild(a); a.click(); a.remove();
    } catch (err) { if (window.console) console.warn('[map-visualizer] export failed', err); }
  });
  map.triggerRepaint();
}

// ---------- view fitting ----------------------------------------------------------------
function zoomTo(e) {
  if (!e.bounds) return;
  var b = e.bounds;
  if (b[0] === b[2] && b[1] === b[3]) map.flyTo({ center: [b[0], b[1]], zoom: Math.max(map.getZoom(), 14) });
  else map.fitBounds([[b[0], b[1]], [b[2], b[3]]], { padding: 40, maxZoom: 16 });
}
function fitInitial(animate) {
  var opts = { padding: { top: 40, bottom: 40, left: collapsed ? 40 : 290, right: 60 }, maxZoom: 16, duration: animate ? 800 : 0 };
  if (wrap.clientWidth < 600) opts.padding = 30;
  if (SPEC.bounds) { map.fitBounds([[SPEC.bounds[0], SPEC.bounds[1]], [SPEC.bounds[2], SPEC.bounds[3]]], opts); return; }
  if (SPEC.center) { map.jumpTo({ center: SPEC.center, zoom: pick(SPEC.zoom, 10), pitch: num(SPEC.pitch, map.getPitch()), bearing: num(SPEC.bearing, 0) }); return; }
  var fitEntries = entries.filter(function (e) { return e.bounds && e.spec.fit !== false && !e.noFit; });
  var forced = entries.filter(function (e) { return e.bounds && e.spec.fit === true; });
  if (forced.length) fitEntries = forced;
  if (!fitEntries.length) { if (animate) map.easeTo({ center: [0, 20], zoom: 1.3 }); return; }
  var b = [Infinity, Infinity, -Infinity, -Infinity];
  fitEntries.forEach(function (e) { extendBounds(b, [e.bounds[0], e.bounds[1]]); extendBounds(b, [e.bounds[2], e.bounds[3]]); });
  b[1] = Math.max(b[1], -85); b[3] = Math.min(b[3], 85);
  if (b[0] === b[2] && b[1] === b[3]) map.jumpTo({ center: [b[0], b[1]], zoom: 14 });
  else map.fitBounds([[b[0], b[1]], [b[2], b[3]]], opts);
}

// ---------- boot --------------------------------------------------------------------------
// Boot on style.load (style parsed), not 'load', which waits for every tile of
// the first frame and so lets one slow tile server hold back all overlays.
var bootDone = false;
map.on('style.load', function () {
  if (bootDone) return;
  bootDone = true;
  if (globeOn) setGlobe();
  var pending = (SPEC.layers || []).map(function (L, i) {
    var e = newEntry(L, i);
    var fn = loaders[L.type];
    if (!fn) { fail(e, new Error('Unknown layer type "' + L.type + '"')); return Promise.resolve(); }
    var r;
    try { r = fn(e); } catch (err) { fail(e, err); return Promise.resolve(); }
    return Promise.resolve(r).then(function () { if (e.state !== 'error') done(e); restack(); }).catch(function (err) { fail(e, err); });
  });
  renderPanel();
  if (SPEC.terrain) setTerrain(true);
  if (SPEC.bounds || SPEC.center) fitInitial(false);
  Promise.all(pending).then(function () {
    if (!SPEC.bounds && !SPEC.center) fitInitial(false);
    renderPanel();
  });
});
map.on('error', function (ev) {
  var err = ev && ev.error;
  var sid = ev && (ev.sourceId || (ev.source && ev.source.id));
  // basemap style JSON failed before boot: style.load would never fire, so fall back to raster OSM
  if (!bootDone && err && !sid && currentBasemap.type === 'style' && err.url && err.url === currentBasemap.url) {
    var osm = basemapIndex.openstreetmap || CFG.basemaps.filter(function (b) { return b.type === 'raster'; })[0];
    if (osm) { currentBasemap = osm; map.setStyle(basemapStyle(osm)); }
    return;
  }
  if (!sid || !err) return;
  var e = entries.filter(function (x) { return x.key === sid; })[0];
  if (e && e.state !== 'error' && !e.tileErrorShown) {
    e.tileErrorShown = true;
    e.note = 'Some tiles failed to load (' + (err.status ? 'HTTP ' + err.status : err.message || 'network/CORS') + ')';
    renderPanel();
  }
});
new ResizeObserver(function () { map.resize(); reportHeight(); }).observe(wrap);
window.__mv = { map: map, entries: entries };
})();
"""

# Runs first: reports the iframe height straight away, then loads MapLibre (and PMTiles when
# needed) asynchronously and starts window.mvMain. A blocked or hanging CDN shows an error.
BOOT_SCRIPT = r"""
(function () {
  // pristine copy of this page (before MapLibre touches the DOM) for the pop-out window
  window.mvPageHtml = '<!DOCTYPE html>' + document.documentElement.outerHTML;
  var CFG = JSON.parse(document.getElementById('mv-config').textContent);
  var msg = document.getElementById('mv-msg');
  function report() {
    var h = document.documentElement.scrollHeight;
    try { parent.postMessage({ type: 'iframe:height', height: h }, '*'); } catch (e) {}
    try { if (window.frameElement) window.frameElement.style.height = h + 'px'; } catch (e) {}
  }
  report();
  window.addEventListener('load', report);
  function load(url) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement('script');
      var timer = setTimeout(reject, 20000);
      s.src = url;
      s.async = true;
      s.onload = function () { clearTimeout(timer); resolve(); };
      s.onerror = function () { clearTimeout(timer); reject(); };
      document.head.appendChild(s);
    });
  }
  var css = document.createElement('link');
  css.rel = 'stylesheet';
  css.href = CFG.maplibreCss;
  document.head.appendChild(css);
  // PMTiles failing only breaks pmtiles layers (they report it), not the whole map
  var pm = CFG.pmtilesJs ? load(CFG.pmtilesJs).catch(function () {}) : Promise.resolve();
  load(CFG.maplibreJs).then(function () { return pm; }).then(function () {
    window.mvMain();
  }, function () {
    msg.className = 'mv-fail';
    msg.textContent = 'Could not load MapLibre GL from ' + CFG.maplibreJs + '. The browser may be blocking that host ' +
      '(proxy, firewall or Content Security Policy). An admin can self-host MapLibre and set the maplibre_js_url / maplibre_css_url valves.';
    report();
  });
})();
"""

_FORBIDDEN_SRCDOC_TOKENS = ("<!--", "-->", "<script", "</script", "<![CDATA[", "]]>")
for _tok in _FORBIDDEN_SRCDOC_TOKENS:
    if _tok in MAP_SCRIPT or _tok in MAP_CSS or _tok in BOOT_SCRIPT:
        raise RuntimeError(f"Map Visualizer: embedded script/CSS contains {_tok!r}, which breaks iframe srcdoc parsing")


# ---------------------------------------------------------------------------
# Spec normalisation (server side)
# ---------------------------------------------------------------------------


def _loads_maybe(value, what: str, warnings: list):
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return json.loads(s)
        except json.JSONDecodeError as exc:
            warnings.append(f"{what} is not valid JSON ({exc.msg} at char {exc.pos}); ignored.")
            return None
    return value


def _host_patterns(raw: str) -> list:
    out = []
    for item in re.split(r"[,\s]+", raw or ""):
        item = item.strip().lower()
        if not item:
            continue
        item = re.sub(r"^[a-z]+://", "", item).split("/")[0]
        out.append(item)
    return out


def _host_allowed(url: str, patterns: list) -> bool:
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    if not host:
        return True  # relative URL -> same origin as Open WebUI
    for p in patterns:
        p = p.split(":")[0]
        if p == "*" or p == host:
            return True
        if p.startswith("*.") and (host.endswith(p[1:]) or host == p[2:]):
            return True
    return False


def _layer_urls(layer: dict) -> list:
    urls = []
    for key in ("url", "legendUrl", "titiler"):
        v = layer.get(key)
        if isinstance(v, str):
            urls.append(v)
    for t in layer.get("tiles") or []:
        if isinstance(t, str):
            urls.append(t)
    return urls


def _guess_type(layer: dict) -> str:
    url = str(layer.get("url") or "").lower()
    path = url.split("?")[0]
    if layer.get("data") is not None:
        return "geojson"
    if "service=wms" in url or layer.get("layers") and "wms" in url:
        return "wms"
    if "service=wfs" in url or layer.get("typeName") or layer.get("typeNames"):
        return "wfs"
    if "service=wmts" in url or "{tilematrix}" in url:
        return "wmts"
    if path.endswith(".pmtiles"):
        return "pmtiles"
    if path.endswith((".tif", ".tiff")):
        return "cog"
    if path.endswith((".geojson", ".json")):
        return "geojson"
    if path.endswith((".pbf", ".mvt")) or layer.get("sourceLayer"):
        return "vectortiles"
    if "/collections/" in path:
        return "ogcapi"
    if path.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")) and "{z}" not in url:
        return "image"
    if "{z}" in url:
        return "xyz"
    return ""


def _num_list(value, n: int):
    value = value if not isinstance(value, str) else re.split(r"[,\s]+", value.strip())
    if not isinstance(value, (list, tuple)) or len(value) != n:
        return None
    try:
        return [float(v) for v in value]
    except (TypeError, ValueError):
        return None


def _normalise_spec(raw: dict, valves) -> tuple:
    """Clean up the model's map spec. Returns (spec, warnings, rejected)."""
    warnings, rejected = [], []
    spec = {
        "title": raw.get("title") or "Map",
        "basemap": raw.get("basemap") or valves.default_basemap,
        "units": raw.get("units") or "metric",
    }
    if isinstance(spec["basemap"], str) and spec["basemap"].lower() in _BASEMAP_IDS:
        spec["basemap"] = _BASEMAP_IDS[spec["basemap"].lower()]
    elif isinstance(spec["basemap"], str) and not re.match(r"^(https?:)?/", spec["basemap"]):
        warnings.append(f"Unknown basemap '{spec['basemap']}', fell back to {valves.default_basemap}.")
        spec["basemap"] = valves.default_basemap

    center = _num_list(raw.get("center"), 2)
    if center:
        if abs(center[1]) > 90 >= abs(center[0]):
            center = [center[1], center[0]]
            warnings.append("center looked like [lat, lon]; swapped to [lon, lat].")
        spec["center"] = center
    bounds = _num_list(raw.get("bounds"), 4)
    if bounds:
        spec["bounds"] = bounds
    for key in ("zoom", "pitch", "bearing"):
        if raw.get(key) is not None:
            try:
                spec[key] = float(raw[key])
            except (TypeError, ValueError):
                warnings.append(f"{key} must be a number; ignored.")
    for key in ("globe", "terrain", "panel", "terrainExaggeration"):
        if raw.get(key) is not None:
            spec[key] = raw[key]

    try:
        height = int(raw.get("height") or valves.default_height)
    except (TypeError, ValueError):
        height = valves.default_height
    spec["height"] = max(240, min(height, 1200))

    patterns = _host_patterns(valves.allowed_hosts) if valves.network_policy == "allowlist" else None
    if patterns is not None and isinstance(spec["basemap"], str):
        bm = next((b for b in BASEMAPS if b["id"] == spec["basemap"]), None)
        bm_urls = (bm.get("tiles") or []) + ([bm["url"]] if bm and bm.get("url") else []) if bm else [spec["basemap"]]
        if any(not _host_allowed(u, patterns) for u in bm_urls if u.startswith("http")):
            warnings.append(f"Basemap {spec['basemap']} is not on the admin allowlist; using None.")
            spec["basemap"] = "None"

    layers_in = _loads_maybe(raw.get("layers"), "layers", warnings) or []
    if isinstance(layers_in, dict):
        layers_in = [layers_in]
    layers = []
    for i, layer in enumerate(layers_in if isinstance(layers_in, list) else []):
        layer = _loads_maybe(layer, f"layers[{i}]", warnings)
        if not isinstance(layer, dict):
            warnings.append(f"layers[{i}] is not an object; skipped.")
            continue
        layer = dict(layer)
        t = str(layer.get("type") or "").strip().lower()
        if "footprint" in t and not layer.get("mode"):
            layer["mode"] = "2d"
        t = _TYPE_ALIASES.get(t, t) or _guess_type(layer)
        if t not in LAYER_TYPES:
            rejected.append(f"layers[{i}] ({layer.get('name') or 'unnamed'}): unknown type '{layer.get('type')}'. Use one of {', '.join(LAYER_TYPES)}.")
            continue
        layer["type"] = t
        layer["name"] = str(layer.get("name") or layer.get("title") or layer.get("layers") or layer.get("typeName") or f"{t} {i + 1}")
        if isinstance(layer.get("style"), str):
            layer["style"] = _loads_maybe(layer["style"], f"layers[{i}].style", warnings) or {}
        if isinstance(layer.get("data"), str) and layer["data"].strip().startswith(("{", "[")):
            layer["data"] = _loads_maybe(layer["data"], f"layers[{i}].data", warnings)
        if layer.get("bounds") is not None:
            layer["bounds"] = _num_list(layer["bounds"], 4)
            if not layer["bounds"]:
                del layer["bounds"]
        needs_url = t not in ("geojson", "buildings") and not layer.get("tiles")
        if needs_url and not layer.get("url"):
            rejected.append(f"layers[{i}] ({layer['name']}): '{t}' layers need a 'url'.")
            continue
        if t == "geojson" and layer.get("data") is None and not layer.get("url"):
            rejected.append(f"layers[{i}] ({layer['name']}): geojson layers need 'data' or 'url'.")
            continue
        bad = [u for u in _layer_urls(layer) if not re.match(r"^(https?://|/)", u, re.I)]
        if bad:
            rejected.append(f"layers[{i}] ({layer['name']}): only http(s) or same-host URLs are allowed (got {bad[0][:80]}).")
            continue
        if patterns is not None:
            blocked = [u for u in _layer_urls(layer) if not _host_allowed(u, patterns)]
            if t == "cog" and not layer.get("titiler") and not _host_allowed(valves.titiler_endpoint, patterns):
                blocked.append(valves.titiler_endpoint)
            if t == "buildings" and not layer.get("url"):
                overture = str(layer.get("source") or "").lower() == "overture"
                for u in ((OVERTURE_CATALOG, OVERTURE_BUILDINGS) if overture else (BUILDINGS_TILES,)):
                    if not _host_allowed(u, patterns):
                        blocked.append(u)
            if blocked:
                host = urllib.parse.urlsplit(blocked[0]).hostname
                rejected.append(f"layers[{i}] ({layer['name']}): host '{host}' is not on the admin allowlist.")
                continue
        layers.append(layer)
    spec["layers"] = layers
    return spec, warnings, rejected


# ---------------------------------------------------------------------------
# HTML / CSP
# ---------------------------------------------------------------------------


def _csp_tag(valves) -> str:
    if valves.network_policy == "open":
        return (
            '<meta http-equiv="Content-Security-Policy" content="'
            "object-src 'none'; form-action 'none'; base-uri 'none'; worker-src blob:; child-src blob:; "
            "frame-src 'self' data: blob: about:; "
            '">'
        )
    hosts = []
    for p in _host_patterns(valves.allowed_hosts):
        hosts.append(p if p == "*" else f"https://{p}")
    for u in (valves.maplibre_js_url, valves.pmtiles_js_url, valves.maplibre_css_url, valves.titiler_endpoint):
        parts = urllib.parse.urlsplit(u)
        if parts.scheme and parts.netloc:
            hosts.append(f"{parts.scheme}://{parts.netloc}")
    src = " ".join(["'self'"] + sorted(set(hosts)))
    return (
        '<meta http-equiv="Content-Security-Policy" content="'
        f"default-src 'self'; script-src 'self' 'unsafe-inline' {src}; style-src 'self' 'unsafe-inline' {src}; "
        f"connect-src {src} data: blob:; img-src {src} data: blob:; font-src {src} data:; "
        "worker-src blob:; child-src blob:; frame-src 'self' about:; object-src 'none'; form-action 'none'; base-uri 'none'; "
        '">'
    )


def _escape_html(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _json_for_html(obj) -> str:
    return (
        json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _build_html(spec: dict, valves) -> str:
    config = {
        "spec": spec,
        "height": spec["height"],
        "basemaps": BASEMAPS,
        "defaultBasemap": valves.default_basemap,
        "glyphs": valves.glyphs_url,
        "font": valves.label_font,
        "titiler": valves.titiler_endpoint,
        "terrainTiles": valves.terrain_tiles,
        "buildingsTiles": BUILDINGS_TILES,
        "overtureCatalog": OVERTURE_CATALOG,
        "overtureBuildings": OVERTURE_BUILDINGS,
        "maplibreJs": valves.maplibre_js_url,
    }
    config["maplibreCss"] = valves.maplibre_css_url
    if any(layer["type"] == "pmtiles" or (layer["type"] == "buildings" and str(layer.get("source") or "").lower() == "overture")
           for layer in spec["layers"]):
        config["pmtilesJs"] = valves.pmtiles_js_url
    # Libraries are loaded by BOOT_SCRIPT, not <script src>: a CDN that hangs behind a proxy
    # would otherwise block the parser and leave Open WebUI's iframe as a blank 150px strip.
    return (
        f'<!DOCTYPE html><html data-mv-build="{_MV_BUILD}"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_escape_html(spec['title'])}</title>"
        f"{_csp_tag(valves)}"
        f"<style>{MAP_CSS}</style>"
        f"</head><body>"
        f'<div id="mv-wrap" style="height:{int(spec["height"])}px"><div id="mv-map"></div>'
        f'<div id="mv-msg">Loading map…</div></div>'
        f'<script type="application/json" id="mv-config">{_json_for_html(config)}</script>'
        f"<script>window.mvMain = function () {{{MAP_SCRIPT}}};</script>"
        f"<script>{BOOT_SCRIPT}</script>"
        f"</body></html>"
    )


def _summarise(spec: dict, warnings: list, rejected: list) -> str:
    lines = [f"Map \"{spec['title']}\" is now displayed to the user (basemap: {spec['basemap']})."]
    if spec["layers"]:
        lines.append("Layers, bottom to top:")
        for i, layer in enumerate(spec["layers"], 1):
            state = "visible" if layer.get("visible", True) is not False else "hidden"
            lines.append(f"  {i}. {layer['name']} [{layer['type']}, {state}]")
    else:
        lines.append("No overlay layers.")
    if rejected:
        lines.append("Rejected layers (not drawn):")
        lines.extend(f"  - {r}" for r in rejected)
    if warnings:
        lines.append("Warnings:")
        lines.extend(f"  - {w}" for w in warnings)
    lines.append(
        "The user can toggle layers, change opacity and switch basemaps in the map panel. "
        "Layers that fail in the browser (CORS, bad layer names, HTTP errors) show a red error in that panel; "
        "you cannot see it, so if the user reports a problem use inspect_ogc_service to check names. "
        "To change the map, call show_map again with the full updated spec. "
        "Describe what the map shows; do not print the spec or code."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# GetCapabilities (server side, SSRF-guarded)
# ---------------------------------------------------------------------------


def _check_public(url: str, allow_private: bool) -> None:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("Only absolute http(s) URLs are supported")
    if allow_private:
        return
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise ValueError(f"Cannot resolve host {parts.hostname}: {exc}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not ip.is_global:
            raise ValueError(
                f"Host {parts.hostname} resolves to a non-public address ({ip}). "
                "An admin can enable 'allow_private_networks' to inspect internal services."
            )


class _GuardedRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, allow_private: bool):
        self.allow_private = allow_private

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_public(newurl, self.allow_private)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _http_get(url: str, allow_private: bool, timeout: int, max_bytes: int = 8_000_000) -> bytes:
    _check_public(url, allow_private)
    opener = urllib.request.build_opener(_GuardedRedirect(allow_private))
    req = urllib.request.Request(url, headers={"User-Agent": f"OpenWebUI-MapVisualizer/{_MV_BUILD}", "Accept": "*/*"})
    with opener.open(req, timeout=timeout) as resp:
        data = resp.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("Capabilities document is larger than 8 MB")
    return data


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _child(node, name):
    for c in node:
        if _local(c.tag) == name:
            return c
    return None


def _children(node, name):
    return [c for c in node if _local(c.tag) == name]


def _text(node, name, default=""):
    c = _child(node, name) if node is not None else None
    return (c.text or "").strip() if c is not None and c.text else default


def _parse_wms(root, search: str, limit: int) -> dict:
    cap = _child(root, "Capability")
    service = _child(root, "Service")
    formats = []
    info_formats = []
    if cap is not None:
        req = _child(cap, "Request")
        gm = _child(req, "GetMap") if req is not None else None
        gfi = _child(req, "GetFeatureInfo") if req is not None else None
        formats = [f.text for f in _children(gm, "Format")] if gm is not None else []
        info_formats = [f.text for f in _children(gfi, "Format")] if gfi is not None else []
    layers = []

    def walk(node, inherited_3857):
        crs = {(c.text or "").strip() for c in node if _local(c.tag) in ("CRS", "SRS")}
        has_3857 = inherited_3857 or bool(crs & {"EPSG:3857", "EPSG:900913", "EPSG:102100"})
        name = _text(node, "Name")
        if name:
            bbox = None
            gb = _child(node, "EX_GeographicBoundingBox")
            if gb is not None:
                try:
                    bbox = [float(_text(gb, k)) for k in ("westBoundLongitude", "southBoundLatitude", "eastBoundLongitude", "northBoundLatitude")]
                except ValueError:
                    bbox = None
            ll = _child(node, "LatLonBoundingBox")
            if bbox is None and ll is not None:
                try:
                    bbox = [float(ll.get(k)) for k in ("minx", "miny", "maxx", "maxy")]
                except (TypeError, ValueError):
                    bbox = None
            layers.append({
                "name": name,
                "title": _text(node, "Title"),
                "queryable": node.get("queryable") == "1",
                "styles": [_text(s, "Name") for s in _children(node, "Style")][:6],
                "epsg3857": has_3857,
                "bounds": [round(v, 5) for v in bbox] if bbox else None,
                "abstract": _text(node, "Abstract")[:160],
            })
        for sub in _children(node, "Layer"):
            walk(sub, has_3857)

    if cap is not None:
        for top in _children(cap, "Layer"):
            walk(top, False)
    return {
        "service": "WMS",
        "version": root.get("version"),
        "title": _text(service, "Title"),
        "getmap_formats": formats[:10],
        "featureinfo_formats": info_formats[:10],
        "layers": layers,
    }


def _parse_wfs(root, search: str, limit: int) -> dict:
    ftl = _child(root, "FeatureTypeList")
    service = _child(root, "ServiceIdentification")
    if service is None:
        service = _child(root, "Service")
    out_formats = set()
    for el in root.iter():
        if _local(el.tag) == "Parameter" and el.get("name", "").lower() == "outputformat":
            out_formats.update((v.text or "").strip() for v in el.iter() if _local(v.tag) == "Value")
        if _local(el.tag) in ("ResultFormat", "OutputFormats"):
            out_formats.update(_local(v.tag) if not (v.text or "").strip() else v.text.strip() for v in el)
    layers = []
    for ft in _children(ftl, "FeatureType") if ftl is not None else []:
        bbox = None
        wgs = _child(ft, "WGS84BoundingBox")
        if wgs is not None:
            try:
                lc = [float(v) for v in _text(wgs, "LowerCorner").split()]
                uc = [float(v) for v in _text(wgs, "UpperCorner").split()]
                bbox = [lc[0], lc[1], uc[0], uc[1]]
            except (ValueError, IndexError):
                bbox = None
        ll = _child(ft, "LatLongBoundingBox")
        if bbox is None and ll is not None:
            try:
                bbox = [float(ll.get(k)) for k in ("minx", "miny", "maxx", "maxy")]
            except (TypeError, ValueError):
                bbox = None
        layers.append({
            "name": _text(ft, "Name"),
            "title": _text(ft, "Title"),
            "default_crs": _text(ft, "DefaultCRS") or _text(ft, "DefaultSRS") or _text(ft, "SRS"),
            "bounds": [round(v, 5) for v in bbox] if bbox else None,
            "abstract": _text(ft, "Abstract")[:160],
        })
    fmts = sorted(f for f in out_formats if f)
    return {
        "service": "WFS",
        "version": root.get("version"),
        "title": _text(service, "Title"),
        "output_formats": fmts[:20],
        "json_output": any("json" in f.lower() for f in fmts),
        "layers": layers,
    }


def _parse_wmts(root, search: str, limit: int) -> dict:
    contents = _child(root, "Contents")
    sets = {}
    for tms in _children(contents, "TileMatrixSet") if contents is not None else []:
        ident = _text(tms, "Identifier")
        crs = _text(tms, "SupportedCRS")
        first = _child(tms, "TileMatrix")
        sets[ident] = {
            "crs": crs,
            "web_mercator": any(code in crs for code in ("3857", "900913", "102100")),
            "first_matrix_id": _text(first, "Identifier") if first is not None else "",
        }
    layers = []
    for lyr in _children(contents, "Layer") if contents is not None else []:
        links = [_text(link, "TileMatrixSet") for link in _children(lyr, "TileMatrixSetLink")]
        templates = [
            r.get("template") for r in _children(lyr, "ResourceURL")
            if r.get("resourceType") == "tile" and r.get("template")
        ]
        merc = [s for s in links if sets.get(s, {}).get("web_mercator")]
        merc_sets = []
        for s in merc:
            first = sets[s]["first_matrix_id"]
            # MapLibre substitutes the plain zoom number, so ids must be "<prefix>0", "<prefix>1", ...
            m = re.match(r"^(.*?)0$", first)
            usable = bool(m) and not (m.group(1) or "").endswith("0")
            merc_sets.append({
                "tileMatrixSet": s,
                "first_matrix_id": first,
                "usable": usable,
                "matrixPrefix": m.group(1) if usable else None,
            })
        layers.append({
            "name": _text(lyr, "Identifier"),
            "title": _text(lyr, "Title"),
            "formats": [f.text for f in _children(lyr, "Format")][:4],
            "styles": [_text(s, "Identifier") for s in _children(lyr, "Style")][:4],
            "web_mercator_sets": merc_sets,
            "rest_template": templates[0] if templates else None,
        })
    return {
        "service": "WMTS",
        "version": root.get("version"),
        "layers": layers,
        "note": "Only Web Mercator sets with usable=true can be displayed (matrix ids must be plain zoom numbers, "
        "optionally prefixed). Zero-padded ids such as '00' are not supported; use the service's WMS instead if it has one.",
    }


def _filter_layers(result: dict, search: str, limit: int) -> dict:
    layers = result.get("layers", [])
    if search:
        s = search.lower()
        # name/title hits first; abstracts are often boilerplate shared by every layer
        hits = [l for l in layers if s in (l.get("name") or "").lower() or s in (l.get("title") or "").lower()]
        layers = hits or [l for l in layers if s in (l.get("abstract") or "").lower()]
    result["layer_count"] = len(layers)
    if len(layers) > limit:
        result["truncated"] = f"Showing {limit} of {len(layers)} layers; pass search= to narrow."
    result["layers"] = layers[:limit]
    return result


def _caps_url(url: str, service: str) -> str:
    parts = urllib.parse.urlsplit(url)
    q = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in ("service", "request", "version")]
    version = {"wms": "1.3.0", "wfs": "2.0.0", "wmts": "1.0.0"}[service]
    q += [("SERVICE", service.upper()), ("REQUEST", "GetCapabilities"), ("VERSION", version)]
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(q), ""))


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


class Tools:
    """Map Visualizer: interactive MapLibre maps rendered inline in chat."""

    class Valves(BaseModel):
        network_policy: Literal["open", "allowlist"] = Field(
            default="open",
            description="open (default): maps may load tiles and data from any host, so any WMS/WFS/tile service works. "
            "allowlist: the map (via CSP) and the server-side checks only allow the hosts in allowed_hosts. "
            "For air-gapped installs use allowlist with self-hosted MapLibre URLs and your internal hosts.",
        )
        allowed_hosts: str = Field(
            default=_DEFAULT_ALLOWED_HOSTS,
            description="Comma-separated hosts for network_policy=allowlist. Wildcards like *.example.com are allowed. "
            "The defaults cover the built-in basemaps, terrain, TiTiler and the MapLibre CDN.",
        )
        default_basemap: str = Field(default="OpenStreetMap", description="Basemap used when the model does not choose one.")
        default_height: int = Field(default=520, description="Default map height in pixels.")
        maplibre_js_url: str = Field(default="https://unpkg.com/maplibre-gl@5.24.0/dist/maplibre-gl.js", description="MapLibre GL JS UMD build (5.x). Point at /static/... to self-host.")
        maplibre_css_url: str = Field(default="https://unpkg.com/maplibre-gl@5.24.0/dist/maplibre-gl.css", description="MapLibre GL CSS.")
        pmtiles_js_url: str = Field(default="https://unpkg.com/pmtiles@4.4.1/dist/pmtiles.js", description="PMTiles UMD build, loaded only when a map uses PMTiles.")
        titiler_endpoint: str = Field(default="https://titiler.xyz", description="TiTiler endpoint used to tile Cloud Optimized GeoTIFFs (cog layers).")
        terrain_tiles: str = Field(default=TERRAIN_TILES, description="Terrarium-encoded elevation tiles for 3D terrain.")
        glyphs_url: str = Field(default=GLYPHS_URL, description="Glyph (font) URL used for labels on raster basemaps.")
        label_font: str = Field(default="Noto Sans Regular", description="Font stack name for labels; must exist on glyphs_url.")
        allow_private_networks: bool = Field(
            default=False,
            description="Let inspect_ogc_service fetch from private/internal IP addresses. Off by default to prevent SSRF.",
        )
        request_timeout: int = Field(default=20, description="Timeout in seconds for inspect_ogc_service requests.")

    def __init__(self):
        self.valves = self.Valves()

    async def show_map(
        self,
        title: str = "Map",
        layers: Optional[list] = None,
        basemap: Optional[str] = None,
        center: Optional[list] = None,
        zoom: Optional[float] = None,
        bounds: Optional[list] = None,
        pitch: Optional[float] = None,
        bearing: Optional[float] = None,
        globe: bool = False,
        terrain: bool = False,
        height: Optional[int] = None,
        __event_emitter__=None,
    ):
        """
        Show an interactive MapLibre map inline in the chat. Use it when the user asks for a map or wants
        to see web map services (WMS, WMTS, WFS, XYZ tiles, OGC API Features), GeoJSON, vector tiles,
        PMTiles or Cloud Optimized GeoTIFFs. Each call draws one new map; to change a map, call it again
        with the complete updated spec. If you are unsure of WMS/WFS/WMTS layer names, call
        inspect_ogc_service first instead of guessing.

        Coordinates are always [longitude, latitude] in WGS84. Leave center/zoom/bounds empty to fit the
        map to the data automatically.

        LAYERS: a list of objects drawn in order, first = bottom, last = top. Every layer accepts:
        name, type, visible (default true), opacity (0-1), minzoom, maxzoom, attribution,
        fit (true = zoom to this layer; false = ignore for auto-fit), bounds [w,s,e,n].
        Types and their own keys:
        - xyz: url "https://.../{z}/{x}/{y}.png" ({s} or {a-c} subdomains ok), tileSize, scheme:"tms".
        - wms: url (service endpoint), layers "a,b", styles, format (image/png), transparent (true),
          version ("1.3.0"), params {extra GetMap params e.g. TIME, CQL_FILTER}, queryable (true: click
          for GetFeatureInfo), infoFormat ("application/json"), legend (true: show GetLegendGraphic).
        - wmts: url = REST template with {TileMatrix}/{TileRow}/{TileCol} (or {z}/{y}/{x}), or the KVP
          endpoint plus layer, tileMatrixSet (Web Mercator set), styleName, format, matrixPrefix
          (e.g. "EPSG:3857:" when matrix ids are prefixed), time (fills {Time}), dimensions {Key: value}.
        - wfs: url, typeName, version ("2.0.0"), maxFeatures (2000), cqlFilter, outputFormat
          ("application/json"), axisOrder ("auto"|"lonlat"|"latlon"), strategy ("bbox" = reload
          for the current view; use for big datasets), loadMinzoom (10).
        - ogcapi: OGC API Features: url to the /collections/{id} (or /items) endpoint, or the API
          root plus collection; limit; strategy "bbox".
        - geojson: data (inline FeatureCollection/Feature/geometry) or url.
        - vectortiles: url (TileJSON) or tiles template; sourceLayer (string or list; optional with TileJSON).
        - pmtiles: url to a .pmtiles archive (vector or raster); sourceLayer optional.
        - cog: url to a Cloud Optimized GeoTIFF; rescale "min,max", colormap (e.g. viridis), bidx [1,2,3], nodata.
        - image: url plus coordinates [[TL],[TR],[BR],[BL]] or bounds.
        - buildings: open building footprints, no url needed. source "openfreemap" (OpenStreetMap, default)
          or "overture" (Overture Maps, latest release; heights from height/num_floors); mode "3d" (default,
          extruded) or "2d" (flat footprints; type "footprints" implies 2d); minzoom (13). Clicking shows attributes.
        VECTOR STYLING (geojson, wfs, ogcapi, vectortiles, pmtiles) via "style":
          color, fillColor, fillOpacity, strokeColor, width, radius, dash [2,2], label (property name),
          labelSize, labelColor, extrude (property name or metres), extrudeScale, filter (MapLibre expression),
          colorBy {field, type "graduated"|"categorical", scheme "quantile"|"equal", classes 5,
          colormap (viridis, plasma, magma, YlOrRd, YlGnBu, Blues, Greens, Reds, RdYlGn, RdBu, Spectral; add _r to reverse),
          colors [...], breaks [...], mapping {value: color}, title}.
          Layers get distinct default colours; colorBy builds a legend automatically.
        "popup": true (all attributes, default), false, or a list of fields to show on click.

        Example layers:
        [{"type":"wms","name":"Precipitation","url":"https://example.com/wms","layers":"precip","opacity":0.7},
         {"type":"wfs","name":"Rivers","url":"https://example.com/wfs","typeName":"ns:rivers","style":{"color":"#1d4ed8","width":2}},
         {"type":"geojson","name":"Sites","data":{"type":"FeatureCollection","features":[...]},"style":{"colorBy":{"field":"category"},"label":"name"}}]

        :param title: Short map title shown in the layer panel.
        :param layers: List of layer objects, bottom to top (see above).
        :param basemap: Keyless basemap: OpenStreetMap (default), OpenStreetMap.HOT, OpenTopoMap, CyclOSM, Esri.WorldImagery, Esri.Hybrid, Esri.WorldTopoMap, Esri.WorldStreetMap, Esri.WorldGrayCanvas, Esri.WorldShadedRelief, Esri.OceanBasemap, OpenFreeMap.Liberty, OpenFreeMap.Bright, OpenFreeMap.Positron, OpenFreeMap.Dark, OpenFreeMap.Fiord, USGS.USImagery, USGS.USTopo, NASAGIBS.BlueMarble, NASAGIBS.EarthAtNight, PDOK.BRT, PDOK.Luchtfoto, None; or any XYZ template / MapLibre style URL.
        :param center: [longitude, latitude] of the initial view.
        :param zoom: Initial zoom level (0-22).
        :param bounds: [west, south, east, north] to fit instead of center/zoom.
        :param pitch: Camera tilt in degrees (0-85).
        :param bearing: Map rotation in degrees.
        :param globe: Use the 3D globe projection.
        :param terrain: Turn on 3D terrain.
        :param height: Map height in pixels (240-1200).
        :return: The map is shown to the user; you get a text summary with any rejected layers.
        """
        raw = {
            "title": title, "layers": layers, "basemap": basemap, "center": center, "zoom": zoom,
            "bounds": bounds, "pitch": pitch, "bearing": bearing, "globe": globe, "terrain": terrain, "height": height,
        }
        spec, warnings, rejected = _normalise_spec(raw, self.valves)
        html = _build_html(spec, self.valves)
        summary = _summarise(spec, warnings, rejected)
        if __event_emitter__:
            await __event_emitter__({"type": "embeds", "data": {"embeds": [html]}})
            return summary
        return HTMLResponse(content=html, headers={"Content-Disposition": "inline"}), summary

    async def inspect_ogc_service(
        self,
        url: str,
        service: Literal["auto", "wms", "wfs", "wmts", "ogcapi"] = "auto",
        search: str = "",
        limit: int = 60,
    ) -> str:
        """
        Read a web map service's capabilities so you can use real layer names in show_map.
        Returns the service title, available layers (name, title, bounds [w,s,e,n], styles) and
        formats. For WMS it says whether a layer supports EPSG:3857 (needed for display) and if it
        is queryable; for WFS whether JSON output is available; for WMTS the Web Mercator tile
        matrix sets and REST templates; for OGC API Features the collections.

        :param url: Service endpoint URL (GetCapabilities parameters are added automatically).
        :param service: wms, wfs, wmts, ogcapi, or auto to try them in turn.
        :param search: Optional case-insensitive filter on layer name/title/abstract.
        :param limit: Maximum number of layers to return.
        :return: JSON summary of the service.
        """
        allow = self.valves.allow_private_networks
        timeout = self.valves.request_timeout
        limit = max(1, min(int(limit or 60), 300))
        if self.valves.network_policy == "allowlist" and not _host_allowed(url, _host_patterns(self.valves.allowed_hosts)):
            return json.dumps({"error": f"Host {urllib.parse.urlsplit(url).hostname} is not on the admin allowlist."})

        lowered = url.lower()
        if service == "auto":
            m = re.search(r"service=(wms|wfs|wmts)", lowered)
            if m:
                order = [m.group(1)]
            elif "wfs" in lowered:
                order = ["wfs", "wms", "wmts"]
            elif "wmts" in lowered:
                order = ["wmts", "wms", "wfs"]
            elif "/collections" in lowered or "ogc" in lowered and "wms" not in lowered:
                order = ["ogcapi", "wms", "wfs"]
            else:
                order = ["wms", "wfs", "wmts", "ogcapi"]
        else:
            order = [service]

        errors = []
        for svc in order:
            try:
                if svc == "ogcapi":
                    base = url.split("?")[0].rstrip("/")
                    base = re.sub(r"/collections(/.*)?$", "", base)
                    data = await asyncio.to_thread(_http_get, base + "/collections?f=json", allow, timeout)
                    doc = json.loads(data)
                    cols = []
                    for c in doc.get("collections", []):
                        ext = (c.get("extent") or {}).get("spatial", {}).get("bbox") or [None]
                        cols.append({"name": c.get("id"), "title": c.get("title"), "bounds": ext[0], "abstract": (c.get("description") or "")[:160]})
                    result = {"service": "OGC API Features", "api_root": base, "layers": cols,
                              "usage": "show_map layer {type:'ogcapi', url: api_root + '/collections/<name>'}"}
                    return json.dumps(_filter_layers(result, search, limit), ensure_ascii=False)
                data = await asyncio.to_thread(_http_get, _caps_url(url, svc), allow, timeout)
                root = ET.fromstring(data)
                tag = _local(root.tag)
                if "ExceptionReport" in tag or "ServiceException" in tag:
                    errors.append(f"{svc.upper()}: {' '.join(t.strip() for t in root.itertext() if t.strip())[:200]}")
                    continue
                parser = {"wms": _parse_wms, "wfs": _parse_wfs, "wmts": _parse_wmts}[svc]
                if svc == "wms" and tag not in ("WMS_Capabilities", "WMT_MS_Capabilities"):
                    errors.append(f"WMS: unexpected root <{tag}>")
                    continue
                if svc == "wfs" and tag != "WFS_Capabilities":
                    errors.append(f"WFS: unexpected root <{tag}>")
                    continue
                if svc == "wmts" and tag != "Capabilities":
                    errors.append(f"WMTS: unexpected root <{tag}>")
                    continue
                result = parser(root, search, limit)
                result["endpoint"] = url.split("?")[0]
                return json.dumps(_filter_layers(result, search, limit), ensure_ascii=False)
            # JSONDecodeError subclasses ValueError, so it must be caught first
            except json.JSONDecodeError:
                errors.append(f"{svc.upper()}: response is not JSON")
            except ET.ParseError as exc:
                errors.append(f"{svc.upper()}: response is not XML ({exc})")
            except ValueError as exc:
                if "non-public" in str(exc) or "resolve" in str(exc) or "Only absolute" in str(exc):
                    return json.dumps({"error": str(exc)})
                errors.append(f"{svc.upper()}: {exc}")
            except urllib.error.HTTPError as exc:
                errors.append(f"{svc.upper()}: HTTP {exc.code} {exc.reason}")
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                errors.append(f"{svc.upper()}: {getattr(exc, 'reason', exc)}")
        return json.dumps({"error": "Could not read capabilities", "attempts": errors})
