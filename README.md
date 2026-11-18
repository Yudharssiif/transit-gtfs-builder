# Transit GTFS Builder

A QGIS plugin that builds a valid **GTFS feed from scratch** from a stops point layer and a routes line layer. It works anywhere in the world and is designed with informal transit in mind (daladalas, matatus, minibuses, boda-boda routes, ferries), where no official feed exists.

Digitize stops and routes in QGIS, set the service pattern, and export a validated `gtfs_feed.zip`. Stop order, `stop_times.txt`, `shapes.txt`, and `frequencies.txt` are generated automatically from the geometry.

> **Status:** experimental (v0.1.0). Test it on a small network first and validate the output with an official GTFS validator before publishing a feed.

## Features

- Build GTFS from QGIS point and line layers, with no spreadsheet editing
- Frequency-based service (`frequencies.txt`, `exact_times=0`), a good fit for informal transit without fixed timetables
- Automatic stop ordering along each route line
- Automatic `stop_times.txt` from distance, average speed, and time at each stop
- Automatic `shapes.txt` with `shape_dist_traveled`
- Estimated end-to-end travel time and departures per direction for every route, from route length, average speed, and stop time
- Fare information (`fare_attributes.txt` and `fare_rules.txt`): fare bands by route distance, plus optional per-route flat fares
- Optional return direction (reverse stop order and shape)
- Per-route overrides for route ID, names, headway, and first and last departure
- Searchable lists of all IANA timezones and 100+ languages
- Full list of GTFS vehicle types (tram, metro, rail, bus, ferry, cable tram, gondola, funicular, trolleybus, monorail, plus common extended types)
- Built-in validator that catches errors and warnings before export
- Button to create empty template layers to digitize
- Any input CRS: layers are reprojected to WGS84 (EPSG:4326) and distances are ellipsoidal

## Requirements

- QGIS 3.22 or newer (Qt5 and Qt6 builds are supported through `qgis.PyQt`)
- No extra Python packages

## Installation

### From a ZIP file

1. Make sure the ZIP contains a single folder named `transit_gtfs_builder` (with `metadata.txt` inside it).
2. In QGIS go to **Plugins > Manage and Install Plugins > Install from ZIP**.
3. Select the ZIP and click **Install Plugin**.

### Manually

Copy the `transit_gtfs_builder` folder into your QGIS plugins directory, then restart QGIS and enable the plugin under **Plugins > Manage and Install Plugins > Installed**.

| OS | Plugins directory |
|---|---|
| Windows | `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins` |
| Linux | `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins` |
| macOS | `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins` |

### From GitHub

GitHub's "Download ZIP" creates a folder named after the repository (for example `repo-main`). QGIS needs the folder to be called `transit_gtfs_builder`, so rename it, or build a clean ZIP:

```bash
zip -r transit_gtfs_builder.zip transit_gtfs_builder -x "*/__pycache__/*"
```

## Quick start

1. Open the plugin from **Plugins > Transit GTFS Builder** or the toolbar icon.
2. **Agency tab:** enter the agency name and URL, choose the timezone, language, and vehicle type, then set the service days and validity dates.
3. **Layers tab:** choose your stops layer and routes layer and map the fields. No layers yet? Click **Create empty stops and routes layers to digitize**, then draw stops and routes.
4. **Service tab:** set the default headway, first and last departure, average speed, and time at each stop. Tick the return-direction box if vehicles run both ways.
5. **Fares tab (optional):** tick **Include fare information**, choose the currency, and enter distance bands (from km, to km, fare).
6. **Export tab:** choose an output folder and click **Validate**. When it passes, click **Build and export**.

## Input data

**Stops layer (points)**

| Field | Required | Notes |
|---|---|---|
| Name field | Recommended | Becomes `stop_name`. Missing names become `Stop <id>`. |
| ID field | Optional | Becomes `stop_id`. Missing IDs become `S0001`, `S0002`, and so on. Duplicates are renamed. |

**Routes layer (lines)**

| Field | Required | Notes |
|---|---|---|
| Route ID | Optional | Defaults to `R1`, `R2`, and so on. |
| Short name | Optional | If both names are empty, the route ID is used as the short name. |
| Long name | Optional | |
| Headway (min) | Optional | Overrides the default headway for that route. |
| Fare | Optional | Flat fare for that route. Overrides the distance bands (for example for a flat-fare electric bus route). |
| First / last departure | Optional | `HH:MM` or `HH:MM:SS`. Hours above 23 are allowed for service past midnight. |

The template layers use the field names `stop_id`, `stop_name`, `route_id`, `short_name`, `long_name`, `headway_min`, `first_dep`, `last_dep`, and `fare`. Fields with these names (or close variants) are selected automatically.

## How it works

1. All stops and routes are reprojected to WGS84.
2. For each route line, every stop within the **stop-to-route distance** (default 75 m) is snapped to the line and ordered by its position along the line. A route needs at least 2 matching stops.
3. Times for the first stop start at `00:00:00`. Each next stop's arrival is the previous departure plus distance divided by average speed. Intermediate stops add the stop time. This is the standard form for frequency-based trips.
4. `frequencies.txt` repeats each trip from the first to the last departure at the headway, with `exact_times=0`.
5. The route length and average speed give the estimated trip time shown in the Export tab log.
6. If fares are enabled, each route gets the fare of the band that contains its length (or its own Fare field value).
7. If the return direction is enabled, a second trip (`direction_id=1`) is created with reversed stops and a reversed shape.

## Output files

| File | Content |
|---|---|
| `agency.txt` | Agency name, URL, timezone, language, phone, email |
| `stops.txt` | Stops in WGS84 |
| `routes.txt` | Routes with the chosen vehicle type |
| `trips.txt` | One trip per route and direction |
| `stop_times.txt` | Relative times and `shape_dist_traveled` (meters) |
| `calendar.txt` | Weekly service days and validity dates |
| `frequencies.txt` | Headway-based service windows |
| `fare_attributes.txt` | Fares with agency ID (only when fares are enabled), formatted with the currency's decimals |
| `fare_rules.txt` | Which route uses which fare |
| `shapes.txt` | Route geometry with `shape_dist_traveled` |
| `feed_info.txt` | Publisher, language, contact email and URL, validity, version |

Files are written as UTF-8 and zipped together.

## Validation

Errors block export; warnings do not.

- **Errors:** empty agency name or timezone, invalid agency URL, invalid agency email, no service days, start date after end date, average speed of 0 or less, no stops, duplicate stop or route IDs, coordinates out of range, no routes built, trips with fewer than 2 stops, non-increasing times, invalid headway or service window, shapes with fewer than 2 points
- **Fare errors:** invalid currency, non-numeric rows, a band with from larger than to, overlapping bands, negative fares
- **Warnings:** routes without a fare, placeholder URL (`example.com`), unknown timezone name, no language, unusual phone number, stops at 0,0, duplicate stop names, stops at identical coordinates, stops not served by any route, headway longer than the service window

## Limitations

- Fares use the GTFS Fares v1 files (`fare_attributes.txt`, `fare_rules.txt`). Fares v2 is not supported yet.
- A route longer than every fare band gets no fare and a warning. Routes between bands use the next band up unless you untick that option.
- Estimated times assume a constant average speed.
- Frequency-based service only. Fixed timetables are not supported yet.
- Each route uses a single line. Multipart lines are merged and the longest part is used.
- Routes that loop back close to themselves can produce a wrong stop order.
- No `transfers.txt`, fares, or accessibility fields.
- Extended vehicle types (such as shared taxi `1501`) are not supported by every GTFS consumer.
- Template layers are temporary memory layers. Export them to GeoPackage to keep them.

## Project structure

```
transit_gtfs_builder/
├── __init__.py       # QGIS entry point
├── plugin.py         # menu and toolbar integration
├── dialog.py         # user interface
├── gtfs_core.py      # feed building, validation, export
├── data.py           # timezones, languages, vehicle types
├── metadata.txt      # plugin metadata
├── icon.svg
└── README.md
```

## Contributing

Issues and pull requests are welcome. When reporting a bug, include your QGIS version, operating system, and the text from the Export tab log.

## License

Released under the GNU General Public License v2.0 or later (GPL-2.0-or-later), which is compatible with QGIS. Add a `LICENSE` file with the full license text to the repository root.

## Author

**Yussuf Waridi** (Street Mappers)
Contact: streetmappers+qgisplugin@gmail.com
