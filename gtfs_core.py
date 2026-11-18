"""Core logic: build a GTFS feed from QGIS layers, validate it, export it."""

import csv
import os
import re
import zipfile
from datetime import date

DAYS = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]

FILES = {
    "agency.txt": [
        "agency_id",
        "agency_name",
        "agency_url",
        "agency_timezone",
        "agency_lang",
        "agency_phone",
        "agency_email",
    ],
    "stops.txt": ["stop_id", "stop_name", "stop_lat", "stop_lon"],
    "routes.txt": [
        "route_id",
        "agency_id",
        "route_short_name",
        "route_long_name",
        "route_type",
    ],
    "trips.txt": [
        "route_id",
        "service_id",
        "trip_id",
        "trip_headsign",
        "direction_id",
        "shape_id",
    ],
    "stop_times.txt": [
        "trip_id",
        "arrival_time",
        "departure_time",
        "stop_id",
        "stop_sequence",
        "shape_dist_traveled",
    ],
    "calendar.txt": ["service_id"] + DAYS + ["start_date", "end_date"],
    "frequencies.txt": [
        "trip_id",
        "start_time",
        "end_time",
        "headway_secs",
        "exact_times",
    ],
    "shapes.txt": [
        "shape_id",
        "shape_pt_lat",
        "shape_pt_lon",
        "shape_pt_sequence",
        "shape_dist_traveled",
    ],
    "fare_attributes.txt": [
        "fare_id",
        "agency_id",
        "price",
        "currency_type",
        "payment_method",
        "transfers",
    ],
    "fare_rules.txt": ["fare_id", "route_id"],
    "feed_info.txt": [
        "feed_publisher_name",
        "feed_publisher_url",
        "feed_lang",
        "feed_contact_email",
        "feed_contact_url",
        "feed_start_date",
        "feed_end_date",
        "feed_version",
    ],
}

TIME_RE = re.compile(r"^(\d{1,2}):([0-5]\d)(?::([0-5]\d))?$")


def parse_time(text):
    m = TIME_RE.match(str(text).strip())
    if not m:
        return None
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3) or 0)


def fmt_time(sec):
    sec = int(round(sec))
    return "%02d:%02d:%02d" % (sec // 3600, (sec % 3600) // 60, sec % 60)


def _val(feature, field):
    if not field:
        return None
    v = feature[field]
    if v is None:
        return None
    s = str(v).strip()
    if s == "" or s == "NULL":
        return None
    return s


def _line_vertices(geom):
    from qgis.core import QgsPointXY

    if geom is None or geom.isEmpty():
        return []
    if geom.isMultipart():
        merged = geom.mergeLines()
        parts = (
            merged.asMultiPolyline()
            if merged.isMultipart()
            else [merged.asPolyline()]
        )
        if not parts:
            return []
        pts = max(parts, key=len)
    else:
        pts = geom.asPolyline()
    out = []
    for p in pts:
        p = QgsPointXY(p)
        if not out or (
            abs(out[-1].x() - p.x()) > 1e-12
            or abs(out[-1].y() - p.y()) > 1e-12
        ):
            out.append(p)
    return out


def build_feed(stops_layer, routes_layer, cfg):
    """Return (feed, log). log is a list of (level, message)."""
    from qgis.core import (
        QgsCoordinateReferenceSystem,
        QgsCoordinateTransform,
        QgsDistanceArea,
        QgsGeometry,
        QgsPointXY,
        QgsProject,
    )

    log = []
    wgs = QgsCoordinateReferenceSystem("EPSG:4326")
    ctx = QgsProject.instance().transformContext()
    da = QgsDistanceArea()
    da.setSourceCrs(wgs, ctx)
    da.setEllipsoid("WGS84")

    # ---- stops
    xf = QgsCoordinateTransform(stops_layer.crs(), wgs, QgsProject.instance())
    stops, seen = [], set()
    for i, f in enumerate(stops_layer.getFeatures(), start=1):
        g = f.geometry()
        if g is None or g.isEmpty():
            log.append(
                (
                    "WARN",
                    "Stop feature %d has no geometry and was skipped." % i,
                )
            )
            continue
        g = QgsGeometry(g)
        g.transform(xf)
        pt = g.asMultiPoint()[0] if g.isMultipart() else g.asPoint()
        sid = _val(f, cfg.get("stop_id_field")) or "S%04d" % i
        if sid in seen:
            new = "%s_%d" % (sid, i)
            log.append(
                (
                    "WARN",
                    "Duplicate stop_id '%s' renamed to '%s'." % (sid, new),
                )
            )
            sid = new
        seen.add(sid)
        name = _val(f, cfg.get("stop_name_field")) or "Stop %s" % sid
        stops.append(
            {
                "stop_id": sid,
                "stop_name": name,
                "stop_lat": round(pt.y(), 7),
                "stop_lon": round(pt.x(), 7),
                "_pt": QgsPointXY(pt.x(), pt.y()),
            }
        )

    # ---- tables
    agency_id = cfg.get("agency_id") or "A1"
    service_id = cfg.get("service_id") or "SVC1"
    t = {name: [] for name in FILES}
    t["agency.txt"].append(
        {
            "agency_id": agency_id,
            "agency_name": cfg["agency_name"],
            "agency_url": cfg["agency_url"],
            "agency_timezone": cfg["agency_timezone"],
            "agency_lang": cfg.get("agency_lang", ""),
            "agency_phone": cfg.get("agency_phone", ""),
            "agency_email": cfg.get("agency_email", ""),
        }
    )
    cal = {
        "service_id": service_id,
        "start_date": cfg["start_date"],
        "end_date": cfg["end_date"],
    }
    for d, on in zip(DAYS, cfg["days"]):
        cal[d] = "1" if on else "0"
    t["calendar.txt"].append(cal)
    t["feed_info.txt"].append(
        {
            "feed_publisher_name": cfg["agency_name"],
            "feed_publisher_url": cfg["agency_url"],
            "feed_lang": cfg.get("agency_lang", ""),
            "feed_contact_email": cfg.get("agency_email", ""),
            "feed_contact_url": cfg["agency_url"],
            "feed_start_date": cfg["start_date"],
            "feed_end_date": cfg["end_date"],
            "feed_version": date.today().strftime("%Y%m%d"),
        }
    )
    t["stops.txt"] = [{k: s[k] for k in FILES["stops.txt"]} for s in stops]

    speed_ms = max(cfg["speed_kmh"], 0.1) * 1000.0 / 3600.0
    dwell = max(cfg["dwell_sec"], 0)
    buf = cfg["buffer_m"]
    rxf = QgsCoordinateTransform(
        routes_layer.crs(), wgs, QgsProject.instance()
    )
    seen_routes = set()
    route_infos = []
    est_sec = 0.0

    for j, f in enumerate(routes_layer.getFeatures(), start=1):
        g = f.geometry()
        if g is None or g.isEmpty():
            log.append(
                (
                    "WARN",
                    "Route feature %d has no geometry and was skipped." % j,
                )
            )
            continue
        g = QgsGeometry(g)
        g.transform(rxf)
        verts = _line_vertices(g)
        if len(verts) < 2:
            log.append(
                (
                    "WARN",
                    "Route feature %d is not a valid line and was skipped."
                    % j,
                )
            )
            continue
        rid = _val(f, cfg.get("route_id_field")) or "R%d" % j
        if rid in seen_routes:
            rid = "%s_%d" % (rid, j)
        seen_routes.add(rid)
        short = _val(f, cfg.get("route_short_field")) or ""
        long_ = _val(f, cfg.get("route_long_field")) or ""
        if not short and not long_:
            short = rid

        # per-route service settings (fall back to defaults)
        headway = cfg["headway_min"]
        hv = _val(f, cfg.get("route_headway_field"))
        if hv:
            try:
                headway = float(hv)
                if headway <= 0:
                    raise ValueError
            except ValueError:
                log.append(
                    (
                        "WARN",
                        "Route %s: bad headway '%s', using default."
                        % (rid, hv),
                    )
                )
                headway = cfg["headway_min"]
        first, last = cfg["first_dep"], cfg["last_dep"]
        for key, label in (
            ("route_first_field", "first"),
            ("route_last_field", "last"),
        ):
            tv = _val(f, cfg.get(key))
            if tv:
                if parse_time(tv) is None:
                    log.append(
                        (
                            "WARN",
                            "Route %s: bad %s departure '%s', using default."
                            % (rid, label, tv),
                        )
                    )
                elif label == "first":
                    first = tv
                else:
                    last = tv

        line = QgsGeometry.fromPolylineXY(verts)
        cum = [0.0]
        for a, b in zip(verts, verts[1:]):
            cum.append(cum[-1] + da.measureLine(a, b))
        total = cum[-1]

        matches = []
        for s in stops:
            _sq, near, after, _side = line.closestSegmentWithContext(s["_pt"])
            dist = da.measureLine(s["_pt"], near)
            if dist <= buf:
                after = max(min(after, len(verts) - 1), 1)
                along = cum[after - 1] + da.measureLine(verts[after - 1], near)
                matches.append((along, s))
        matches.sort(key=lambda m: m[0])
        if len(matches) < 2:
            log.append(
                (
                    "WARN",
                    "Route %s: fewer than 2 stops within %d m of the line; "
                    "skipped." % (rid, buf),
                )
            )
            continue

        t["routes.txt"].append(
            {
                "route_id": rid,
                "agency_id": agency_id,
                "route_short_name": short,
                "route_long_name": long_,
                "route_type": cfg["route_type"],
            }
        )
        directions = [0, 1] if cfg["both_directions"] else [0]
        for d in directions:
            if d == 0:
                seq = [(a, s) for a, s in matches]
                shape_pts = list(zip(verts, cum))
            else:
                seq = [(total - a, s) for a, s in reversed(matches)]
                shape_pts = [
                    (v, total - c) for v, c in reversed(list(zip(verts, cum)))
                ]
            trip_id = "%s_%d" % (rid, d)
            shape_id = "SH_%s_%d" % (rid, d)
            t["trips.txt"].append(
                {
                    "route_id": rid,
                    "service_id": service_id,
                    "trip_id": trip_id,
                    "trip_headsign": seq[-1][1]["stop_name"],
                    "direction_id": d,
                    "shape_id": shape_id,
                }
            )
            clock = 0.0
            for k, (along, s) in enumerate(seq):
                if k == 0:
                    arr = dep = 0.0
                else:
                    arr = clock + (along - seq[k - 1][0]) / speed_ms
                    dep = arr + (dwell if k < len(seq) - 1 else 0)
                clock = dep
                t["stop_times.txt"].append(
                    {
                        "trip_id": trip_id,
                        "arrival_time": fmt_time(arr),
                        "departure_time": fmt_time(dep),
                        "stop_id": s["stop_id"],
                        "stop_sequence": k + 1,
                        "shape_dist_traveled": round(along, 1),
                    }
                )
            if d == 0:
                est_sec = clock
            t["frequencies.txt"].append(
                {
                    "trip_id": trip_id,
                    "start_time": fmt_time(parse_time(first)),
                    "end_time": fmt_time(parse_time(last)),
                    "headway_secs": int(round(headway * 60)),
                    "exact_times": 0,
                }
            )
            for n, (p, c) in enumerate(shape_pts, start=1):
                t["shapes.txt"].append(
                    {
                        "shape_id": shape_id,
                        "shape_pt_lat": round(p.y(), 7),
                        "shape_pt_lon": round(p.x(), 7),
                        "shape_pt_sequence": n,
                        "shape_dist_traveled": round(c, 1),
                    }
                )

        window = parse_time(last) - parse_time(first)
        n_dep = int(window // (headway * 60)) + 1 if window > 0 else 0
        log.append(
            (
                "INFO",
                "Route %s: %d stops, %.2f km, estimated %.0f min end to end "
                "(%g km/h, %d s stops), about %d departures per direction."
                % (
                    rid,
                    len(matches),
                    total / 1000.0,
                    est_sec / 60.0,
                    cfg["speed_kmh"],
                    dwell,
                    n_dep,
                ),
            )
        )
        flat_fare = None
        fv = _val(f, cfg.get("route_fare_field"))
        if fv:
            try:
                flat_fare = float(fv.replace(",", ""))
                if flat_fare < 0:
                    raise ValueError
            except ValueError:
                flat_fare = None
                log.append(
                    ("WARN", "Route %s: bad fare '%s', ignored." % (rid, fv))
                )
        route_infos.append(
            {
                "route_id": rid,
                "length_km": total / 1000.0,
                "flat_fare": flat_fare,
            }
        )

    fares = cfg.get("fares") or {}
    if fares.get("enabled"):
        _build_fares(t, route_infos, fares, log, agency_id)
    return {"tables": t}, log


def format_price(value, currency):
    """Format a price with the ISO 4217 number of decimals."""
    from .data import CURRENCY_DIGITS

    return "%.*f" % (CURRENCY_DIGITS.get(currency, 2), value)


def pick_band(length_km, bands, round_up=True):
    """Return (band, exact). band is (from_km, to_km, price) or None."""
    ordered = sorted(bands)
    for b in ordered:
        if b[0] <= length_km <= b[1]:
            return b, True
    if round_up:
        for b in ordered:
            if b[0] > length_km:
                return b, False
    return None, False


def _build_fares(t, infos, fares, log, agency_id):
    cur = fares["currency"]
    ids = {}
    for info in infos:
        rid, km = info["route_id"], info["length_km"]
        price, why = None, ""
        if info["flat_fare"] is not None:
            price, why = info["flat_fare"], "route fare field"
        elif fares.get("bands"):
            band, exact = pick_band(km, fares["bands"], fares["round_up"])
            if band:
                price = band[2]
                why = "%g-%g km band" % (band[0], band[1])
                if not exact:
                    why += ", next band up"
        if price is None:
            log.append(
                ("WARN", "Route %s (%.1f km): no matching fare." % (rid, km))
            )
            continue
        key = round(price, 4)
        if key not in ids:
            ids[key] = "FARE_%g" % price
            t["fare_attributes.txt"].append(
                {
                    "fare_id": ids[key],
                    "agency_id": agency_id,
                    "price": format_price(price, cur),
                    "currency_type": cur,
                    "payment_method": fares["payment_method"],
                    "transfers": fares["transfers"],
                }
            )
        t["fare_rules.txt"].append({"fare_id": ids[key], "route_id": rid})
        log.append(
            (
                "INFO",
                "Route %s: fare %s %s (%s)."
                % (rid, format_price(price, cur), cur, why),
            )
        )


def validate(feed, cfg):
    """Return a list of (level, message). Level: ERROR, WARN, OK."""
    t = feed["tables"]
    out = []

    def err(m):
        out.append(("ERROR", m))

    def warn(m):
        out.append(("WARN", m))

    ag = t["agency.txt"][0]
    if not str(ag["agency_name"]).strip():
        err("Agency name is empty.")
    if not re.match(r"^https?://", str(ag["agency_url"]).strip()):
        err("Agency URL must start with http:// or https://.")
    elif "example.com" in ag["agency_url"]:
        warn(
            "Agency URL is a placeholder (example.com). "
            "Replace it before publishing."
        )
    if not str(ag["agency_timezone"]).strip():
        err("Agency timezone is empty.")
    else:
        from .data import TIMEZONES

        if ag["agency_timezone"] not in TIMEZONES:
            warn(
                "Timezone '%s' is not a known IANA timezone."
                % ag["agency_timezone"]
            )
    email = str(ag["agency_email"]).strip()
    if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        err("Agency email '%s' is not a valid email address." % email)
    phone = str(ag["agency_phone"]).strip()
    if phone and not re.match(r"^\+?[0-9][0-9 ()./-]{4,}$", phone):
        warn(
            "Agency phone '%s' looks unusual. Use digits, e.g. +255 ..."
            % phone
        )
    if not str(ag["agency_lang"]).strip():
        warn("No language selected for the feed.")

    cal = t["calendar.txt"][0]
    if not any(cal[d] == "1" for d in DAYS):
        err("No service days selected.")
    if cal["start_date"] > cal["end_date"]:
        err("Service start date is after the end date.")
    if cfg["speed_kmh"] <= 0:
        err("Average speed must be greater than 0.")

    stops = t["stops.txt"]
    if not stops:
        err("No stops found in the stops layer.")
    ids = [s["stop_id"] for s in stops]
    if len(ids) != len(set(ids)):
        err("stop_id values are not unique.")
    names, coords = {}, {}
    for s in stops:
        if not (-90 <= s["stop_lat"] <= 90 and -180 <= s["stop_lon"] <= 180):
            err("Stop %s has coordinates out of range." % s["stop_id"])
        if s["stop_lat"] == 0 and s["stop_lon"] == 0:
            warn("Stop %s is at 0,0. Check the layer CRS." % s["stop_id"])
        names.setdefault(s["stop_name"], []).append(s["stop_id"])
        coords.setdefault((s["stop_lat"], s["stop_lon"]), []).append(
            s["stop_id"]
        )
    for n, l in names.items():
        if len(l) > 1:
            warn("Stops share the name '%s': %s." % (n, ", ".join(l[:4])))
    for c, l in coords.items():
        if len(l) > 1:
            warn("Stops at identical location: %s." % ", ".join(l[:4]))

    if not t["routes.txt"]:
        err(
            "No routes could be built. Check the stop buffer distance "
            "and layer CRS."
        )
    rids = [r["route_id"] for r in t["routes.txt"]]
    if len(rids) != len(set(rids)):
        err("route_id values are not unique.")

    used = {r["stop_id"] for r in t["stop_times.txt"]}
    unused = [i for i in ids if i not in used]
    if unused and t["routes.txt"]:
        warn(
            "%d stop(s) are not served by any route: %s%s"
            % (
                len(unused),
                ", ".join(unused[:6]),
                "..." if len(unused) > 6 else "",
            )
        )

    by_trip = {}
    for r in t["stop_times.txt"]:
        by_trip.setdefault(r["trip_id"], []).append(r)
    for trip, rows in by_trip.items():
        if len(rows) < 2:
            err("Trip %s has fewer than 2 stops." % trip)
        prev = -1
        for r in rows:
            a, d = parse_time(r["arrival_time"]), parse_time(
                r["departure_time"]
            )
            if a is None or d is None or a < prev or d < a:
                err(
                    "Trip %s has non-increasing times at stop %s."
                    % (trip, r["stop_id"])
                )
                break
            prev = d

    for fr in t["frequencies.txt"]:
        s, e = parse_time(fr["start_time"]), parse_time(fr["end_time"])
        if fr["headway_secs"] <= 0:
            err("Trip %s: headway must be positive." % fr["trip_id"])
        if s is None or e is None or s >= e:
            err(
                "Trip %s: first departure must be before last departure."
                % fr["trip_id"]
            )
        elif fr["headway_secs"] > (e - s) and fr["headway_secs"] > 0:
            warn(
                "Trip %s: headway is longer than the service window."
                % fr["trip_id"]
            )

    counts = {}
    for r in t["shapes.txt"]:
        counts[r["shape_id"]] = counts.get(r["shape_id"], 0) + 1
    for sh, n in counts.items():
        if n < 2:
            err("Shape %s has fewer than 2 points." % sh)

    fc = cfg.get("fares") or {}
    if fc.get("enabled"):
        if not re.match(r"^[A-Z]{3}$", str(fc.get("currency", ""))):
            err("Fare currency must be a 3-letter code such as TZS.")
        for m in fc.get("parse_errors", []):
            err(m)
        bands = sorted(fc.get("bands", []))
        for b in bands:
            if b[0] > b[1]:
                err("Fare band %g-%g km: 'from' is larger than 'to'." % b[:2])
            if b[2] < 0:
                err("Fare band %g-%g km has a negative fare." % b[:2])
        for a, b in zip(bands, bands[1:]):
            if b[0] <= a[1]:
                err(
                    "Fare bands %g-%g km and %g-%g km overlap."
                    % (a[0], a[1], b[0], b[1])
                )
        if not bands and not fc.get("has_route_field"):
            warn("Fares are enabled but there are no fare bands.")
        ruled = {r["route_id"] for r in t["fare_rules.txt"]}
        missing = [r for r in rids if r not in ruled]
        if missing:
            warn(
                "%d route(s) have no fare: %s"
                % (len(missing), ", ".join(missing[:6]))
            )

    if not any(lvl == "ERROR" for lvl, _ in out):
        out.append(
            (
                "OK",
                "Passed validation: %d stops, %d routes, %d trips."
                % (len(stops), len(t["routes.txt"]), len(t["trips.txt"])),
            )
        )
    return out


def export_feed(feed, folder, zip_name):
    os.makedirs(folder, exist_ok=True)
    paths = []
    for fname, rows in feed["tables"].items():
        if not rows:
            continue
        p = os.path.join(folder, fname)
        with open(p, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(
                fh, fieldnames=FILES[fname], extrasaction="ignore"
            )
            w.writeheader()
            w.writerows(rows)
        paths.append(p)
    if not zip_name.lower().endswith(".zip"):
        zip_name += ".zip"
    zp = os.path.join(folder, zip_name)
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for p in paths:
            z.write(p, os.path.basename(p))
    return zp
