# Examples

Each file is a complete set of arguments for `show_map` (title, layers, basemap and view). All services are public and keyless. Layer names and URLs were checked against the live services; services can change, so if one fails ask the model to run `inspect_ogc_service` again.

Paste the JSON into a prompt ("call show_map with this") to test it, or use the prompt below to see how the model builds it.

| File | Shows | Prompt |
| --- | --- | --- |
| [01-netherlands-pdok.json](01-netherlands-pdok.json) | PDOK background map, CBS provinces (WMS) and municipalities (WFS, hidden until ticked) | "Show the Dutch provinces and municipalities from the PDOK CBS Gebiedsindelingen services on the PDOK map." |
| [02-nasa-true-colour.json](02-nasa-true-colour.json) | NASA GIBS MODIS true colour for 1 August 2024 (WMTS with a date) on a globe | "Show MODIS true-colour imagery from NASA GIBS for 1 August 2024 on a globe." |
| [03-dutch-windmills.json](03-dutch-windmills.json) | OGC API Features from the pygeoapi demo, coloured by mill type | "Map the windmills in the pygeoapi demo and colour them by type." |
| [04-florence-pmtiles.json](04-florence-pmtiles.json) | A vector PMTiles archive of Florence, no basemap | "Show this PMTiles file of Florence: https://pmtiles.io/protomaps(vector)ODbL_firenze.pmtiles" |
| [05-libya-cog.json](05-libya-cog.json) | A Cloud Optimized GeoTIFF of Derna, Libya, over Esri imagery | "Show this COG over satellite imagery: https://github.com/opengeos/data/releases/download/raster/Libya-2023-07-01.tif" |
| [06-european-cities-colorby.json](06-european-cities-colorby.json) | Inline GeoJSON points with graduated `colorBy` and a legend | "Map 12 European capitals and big cities, sized and coloured by approximate population." |

Notes:

- Example 01: the municipalities layer is about 2 MB of GeoJSON, which is why it starts hidden.
- Example 05: the `bounds` are set because TiTiler's bounds lookup is not always available. The COG is tiled by the TiTiler server in the `titiler_endpoint` valve (`titiler.xyz` by default).
- Example 06: the populations are rounded approximations for illustration.
