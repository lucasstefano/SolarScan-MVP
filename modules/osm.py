# modules/osm.py
"""
Contextualização territorial via OpenStreetMap (OSM)

Saída (compatível com spatial_join.py):
[
  {"geometry": shapely.geometry.Polygon|MultiPolygon, "landuse": "residential|commercial|industrial|unknown"},
  ...
]

Upgrades:
- Consulta mais sinais além de landuse:
  building:use, usage, craft, service, tourism, leisure, shop, office, amenity, industrial, power, man_made
- Normalização mais agressiva para reduzir unknown (com heurísticas conservadoras)
"""

from __future__ import annotations

import time
import math
import logging
from typing import Any, Dict, List, Optional, Tuple

import requests
import certifi
from requests.exceptions import RequestException, SSLError

from shapely.geometry import Polygon, Point
from shapely.validation import make_valid
from shapely.affinity import scale


# --------------------------------------------------------------------------- #
# Tuning
# --------------------------------------------------------------------------- #

MIN_CLASSIFIED_POLYGONS = 10
UNKNOWN_RATIO_THRESHOLD = 0.70
POI_BUFFER_M = 25.0
MERGE_FALLBACK = True


logger = logging.getLogger("solarscan.osm")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", "%H:%M:%S"))
    logger.addHandler(handler)
    logger.propagate = False


_overpass_env = "https://overpass.kumi.systems/api/interpreter"

OVERPASS_ENDPOINTS: List[str] = [
    _overpass_env,
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.nchc.org.tw/api/interpreter",
]
OVERPASS_ENDPOINTS = [u for u in OVERPASS_ENDPOINTS if u]


def _build_overpass_query_landuse(lat: float, lon: float, raio_m: float) -> str:
    r = int(max(1.0, float(raio_m)))
    return f"""
    [out:json][timeout:25];
    (
      way["landuse"](around:{r},{lat},{lon});
      relation["landuse"](around:{r},{lat},{lon});
    );
    out geom;
    """


def _build_overpass_query_fallback(lat: float, lon: float, raio_m: float) -> str:
    r = int(max(1.0, float(raio_m)))
    return f"""
    [out:json][timeout:25];
    (
      way["building"](around:{r},{lat},{lon});
      relation["building"](around:{r},{lat},{lon});

      way["building:use"](around:{r},{lat},{lon});
      relation["building:use"](around:{r},{lat},{lon});

      way["usage"](around:{r},{lat},{lon});
      relation["usage"](around:{r},{lat},{lon});

      node["shop"](around:{r},{lat},{lon});
      way["shop"](around:{r},{lat},{lon});
      relation["shop"](around:{r},{lat},{lon});

      node["office"](around:{r},{lat},{lon});
      way["office"](around:{r},{lat},{lon});
      relation["office"](around:{r},{lat},{lon});

      node["amenity"](around:{r},{lat},{lon});
      way["amenity"](around:{r},{lat},{lon});
      relation["amenity"](around:{r},{lat},{lon});

      node["craft"](around:{r},{lat},{lon});
      way["craft"](around:{r},{lat},{lon});
      relation["craft"](around:{r},{lat},{lon});

      node["service"](around:{r},{lat},{lon});
      way["service"](around:{r},{lat},{lon});
      relation["service"](around:{r},{lat},{lon});

      node["tourism"](around:{r},{lat},{lon});
      way["tourism"](around:{r},{lat},{lon});
      relation["tourism"](around:{r},{lat},{lon});

      node["leisure"](around:{r},{lat},{lon});
      way["leisure"](around:{r},{lat},{lon});
      relation["leisure"](around:{r},{lat},{lon});

      node["industrial"](around:{r},{lat},{lon});
      way["industrial"](around:{r},{lat},{lon});
      relation["industrial"](around:{r},{lat},{lon});

      node["man_made"="works"](around:{r},{lat},{lon});
      way["man_made"="works"](around:{r},{lat},{lon});
      relation["man_made"="works"](around:{r},{lat},{lon});

      node["power"](around:{r},{lat},{lon});
      way["power"](around:{r},{lat},{lon});
      relation["power"](around:{r},{lat},{lon});
    );
    out geom;
    """


def _post_overpass(query: str) -> Dict[str, Any]:
    last_err: Optional[Exception] = None

    for url in OVERPASS_ENDPOINTS:
        for attempt in range(1, 4):
            try:
                logger.info("OSM | tentando endpoint=%s (tentativa %d/3)", url, attempt)

                resp = requests.post(
                    url,
                    data={"data": query},
                    headers={"User-Agent": "SolarScan/1.0 (requests)"},
                    timeout=(10, 60),
                    verify=certifi.where(),
                )
                resp.raise_for_status()
                return resp.json()

            except SSLError as e:
                last_err = e
                logger.warning("OSM | SSL falhou no endpoint=%s | %s", url, str(e))
                break
            except ValueError as e:
                last_err = e
                logger.warning("OSM | JSON inválido endpoint=%s | %s", url, str(e))
                time.sleep(0.5 * attempt)
            except RequestException as e:
                last_err = e
                logger.warning("OSM | request falhou endpoint=%s | %s", url, str(e))
                time.sleep(0.6 * attempt)

    raise RuntimeError(f"Overpass API error: {last_err}")


def _coords_from_geometry(geom_list: Any) -> Optional[List[Tuple[float, float]]]:
    if not isinstance(geom_list, list) or len(geom_list) < 3:
        return None

    coords: List[Tuple[float, float]] = []
    for p in geom_list:
        if not isinstance(p, dict) or "lat" not in p or "lon" not in p:
            continue
        coords.append((float(p["lon"]), float(p["lat"])))

    if len(coords) < 3:
        return None
    if coords[0] != coords[-1]:
        coords.append(coords[0])
    if len(coords) < 4:
        return None
    return coords


def _safe_make_polygon(coords: List[Tuple[float, float]]):
    try:
        poly = Polygon(coords)
        if poly.is_empty:
            return None
        if not poly.is_valid:
            poly = make_valid(poly)
        if getattr(poly, "geom_type", None) not in ("Polygon", "MultiPolygon"):
            return None
        return poly
    except Exception:
        return None


def _buffer_node_as_polygon(lat: float, lon: float, radius_m: float):
    try:
        dlat = float(radius_m) / 111_320.0
        dlon = float(radius_m) / (111_320.0 * max(1e-6, math.cos(math.radians(float(lat)))))

        circ = Point(float(lon), float(lat)).buffer(1.0, resolution=16)
        poly = scale(circ, xfact=dlon, yfact=dlat, origin=(float(lon), float(lat)))

        if not poly.is_valid:
            poly = make_valid(poly)
        if getattr(poly, "geom_type", None) not in ("Polygon", "MultiPolygon"):
            return None
        return poly
    except Exception:
        return None


_LANDUSE_TO_CLASS = {
    "residential": "residential",
    "house": "residential",

    "commercial": "commercial",
    "retail": "commercial",

    "industrial": "industrial",
    "construction": "industrial",
    "brownfield": "industrial",
    "quarry": "industrial",
}

_RES_BUILDINGS = {
    "house", "apartments", "residential", "terrace", "semidetached_house",
    "bungalow", "detached", "dormitory",
    "garage", "garages", "shed", "hut",
}
_COM_BUILDINGS = {"commercial", "retail", "office", "supermarket", "kiosk"}
_IND_BUILDINGS = {"industrial", "warehouse", "factory", "manufacture"}

_COM_USAGE = {"commercial", "retail", "office", "services", "service"}
_IND_USAGE = {"industrial", "warehouse", "logistics", "manufacturing"}
_RES_USAGE = {"residential", "apartments", "house", "housing"}

_AMENITY_EXCEPT_UNKNOWN = {"grave_yard", "cemetery", "shelter"}


def _normalize_from_tags(tags: Dict[str, Any]) -> str:
    t: Dict[str, str] = {}
    for k, v in (tags or {}).items():
        try:
            t[str(k)] = str(v)
        except Exception:
            continue

    lu = (t.get("landuse") or "").strip().lower()
    if lu:
        return _LANDUSE_TO_CLASS.get(lu, "unknown")

    p = (t.get("power") or "").strip().lower()
    if p in {"substation", "plant", "generator"}:
        return "industrial"
    if (t.get("man_made") or "").strip().lower() == "works":
        return "industrial"
    if "industrial" in t:
        return "industrial"

    bu = (t.get("building:use") or "").strip().lower()
    if bu in _IND_USAGE:
        return "industrial"
    if bu in _COM_USAGE:
        return "commercial"
    if bu in _RES_USAGE:
        return "residential"

    us = (t.get("usage") or "").strip().lower()
    if us in _IND_USAGE:
        return "industrial"
    if us in _COM_USAGE:
        return "commercial"
    if us in _RES_USAGE:
        return "residential"

    b = (t.get("building") or "").strip().lower()
    if b in _IND_BUILDINGS:
        return "industrial"
    if b in _COM_BUILDINGS:
        return "commercial"
    if b in _RES_BUILDINGS:
        return "residential"

    if any(k in t for k in ("craft", "service", "shop", "office", "tourism", "leisure")):
        return "commercial"

    if "amenity" in t:
        a = (t.get("amenity") or "").strip().lower()
        if a and a in _AMENITY_EXCEPT_UNKNOWN:
            return "unknown"
        return "commercial"

    if b in {"yes", "building"}:
        if any(k.startswith("addr:") for k in t.keys()):
            return "residential"
        return "residential"

    if any(v.strip().lower() in {"warehouse", "construction"} for v in t.values()):
        return "industrial"

    return "unknown"


def _count_classes(polygons: List[Dict[str, Any]]) -> Dict[str, int]:
    c = {"residential": 0, "commercial": 0, "industrial": 0, "unknown": 0}
    for p in polygons or []:
        k = str(p.get("landuse", "unknown"))
        if k not in c:
            k = "unknown"
        c[k] += 1
    return c


def parse_polygons_landuse(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    elements = (data or {}).get("elements", [])
    if not isinstance(elements, list):
        return []

    polygons: List[Dict[str, Any]] = []
    for el in elements:
        if not isinstance(el, dict):
            continue
        tags = el.get("tags") or {}
        if not isinstance(tags, dict):
            tags = {}

        coords = _coords_from_geometry(el.get("geometry"))
        if not coords:
            continue

        poly = _safe_make_polygon(coords)
        if poly is None:
            continue

        cls = _normalize_from_tags(tags)
        polygons.append({"geometry": poly, "landuse": cls})

    return polygons


def parse_polygons_fallback(data: Dict[str, Any], poi_buffer_m: float = POI_BUFFER_M) -> List[Dict[str, Any]]:
    elements = (data or {}).get("elements", [])
    if not isinstance(elements, list):
        return []

    polygons: List[Dict[str, Any]] = []
    for el in elements:
        if not isinstance(el, dict):
            continue

        tags = el.get("tags") or {}
        if not isinstance(tags, dict):
            tags = {}

        cls = _normalize_from_tags(tags)

        coords = _coords_from_geometry(el.get("geometry"))
        if coords:
            poly = _safe_make_polygon(coords)
            if poly is not None:
                polygons.append({"geometry": poly, "landuse": cls})
                continue

        if el.get("type") == "node" and "lat" in el and "lon" in el:
            poly = _buffer_node_as_polygon(float(el["lat"]), float(el["lon"]), float(poi_buffer_m))
            if poly is not None:
                polygons.append({"geometry": poly, "landuse": cls})

    return polygons


def obter_poligonos_osm(lat: float, lon: float, raio_m: float) -> Dict[str, Any]:
    logger.info("OSM | consulta iniciada (raio=%.0fm)", float(raio_m))

    try:
        data = _post_overpass(_build_overpass_query_landuse(lat, lon, raio_m))
        polygons = parse_polygons_landuse(data)

        counts = _count_classes(polygons)
        classified = counts["residential"] + counts["commercial"] + counts["industrial"]
        total = int(len(polygons))
        unknown_ratio = (float(counts.get("unknown", 0)) / float(total)) if total else 1.0

        logger.info(
            "OSM | landuse normalizado | total=%d | res=%d com=%d ind=%d unk=%d",
            len(polygons), counts["residential"], counts["commercial"], counts["industrial"], counts["unknown"]
        )
        logger.info("OSM | unknown_ratio=%.2f", unknown_ratio)

        need_fallback = (classified < MIN_CLASSIFIED_POLYGONS) or (unknown_ratio >= UNKNOWN_RATIO_THRESHOLD)
        if need_fallback:
            reason = []
            if classified < MIN_CLASSIFIED_POLYGONS:
                reason.append(f"classes úteis baixas ({classified} < {MIN_CLASSIFIED_POLYGONS})")
            if unknown_ratio >= UNKNOWN_RATIO_THRESHOLD:
                reason.append(f"unknown alto ({unknown_ratio:.0%} >= {UNKNOWN_RATIO_THRESHOLD:.0%})")

            logger.info("OSM | ativando fallback buildings/POIs | %s", " + ".join(reason))
            data_fb = _post_overpass(_build_overpass_query_fallback(lat, lon, raio_m))
            fb_polys = parse_polygons_fallback(data_fb, poi_buffer_m=POI_BUFFER_M)

            if MERGE_FALLBACK:
                polygons = polygons + fb_polys
            else:
                polygons = fb_polys

        logger.info("OSM | polígonos válidos=%d", len(polygons))
        return {"polygons": polygons, "success": True}

    except Exception as e:
        err = str(e)
        logger.warning("OSM | falhou: %s", err)
        return {"polygons": [], "success": False, "error": err}
