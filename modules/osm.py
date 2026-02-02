"""
MÓDULO 5 — osm.py
Contextualização territorial via OpenStreetMap (OSM)

Saída (compatível com spatial_join.py):
[
  {"geometry": shapely.geometry.Polygon|MultiPolygon, "landuse": "residential|commercial|industrial|unknown"},
  ...
]

Estratégia:
1) Busca landuse=* (ways/relations) e NORMALIZA p/ {residential, commercial, industrial, unknown}
2) Se res+com+ind for baixo, roda FALLBACK gratuito via OSM:
   - building=* (ways/relations -> polígonos)
   - POIs (nodes) shop/office/amenity/industrial/power/man_made=works -> buffer -> polígonos
3) (Por padrão) faz MERGE: landuse normalizado + fallback para cobrir lacunas.
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
# Tuning fácil
# --------------------------------------------------------------------------- #

# Se após normalizar o landuse, a soma (res+com+ind) for menor que isso,
# ativa fallback buildings/POIs.
MIN_CLASSIFIED_POLYGONS = 10

# Buffer (metros) para POIs (nodes) virarem polígonos.
POI_BUFFER_M = 25.0

# Se True: combina (landuse normalizado) + (fallback) ao invés de substituir
MERGE_FALLBACK = True


# --------------------------------------------------------------------------- #
# Logger
# --------------------------------------------------------------------------- #

logger = logging.getLogger("solarscan.osm")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", "%H:%M:%S"))
    logger.addHandler(handler)
    logger.propagate = False


# --------------------------------------------------------------------------- #
# Overpass endpoints (fallback)
# --------------------------------------------------------------------------- #

_overpass_env = "https://overpass.kumi.systems/api/interpreter"

OVERPASS_ENDPOINTS: List[str] = [
    _overpass_env,
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.nchc.org.tw/api/interpreter",
]
OVERPASS_ENDPOINTS = [u for u in OVERPASS_ENDPOINTS if u]


# --------------------------------------------------------------------------- #
# Query builders
# --------------------------------------------------------------------------- #

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

      node["shop"](around:{r},{lat},{lon});
      node["office"](around:{r},{lat},{lon});
      node["amenity"](around:{r},{lat},{lon});

      node["industrial"](around:{r},{lat},{lon});
      node["man_made"="works"](around:{r},{lat},{lon});

      node["power"](around:{r},{lat},{lon});
      way["power"](around:{r},{lat},{lon});
      relation["power"](around:{r},{lat},{lon});
    );
    out geom;
    """


# --------------------------------------------------------------------------- #
# Overpass request
# --------------------------------------------------------------------------- #

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


# --------------------------------------------------------------------------- #
# Geometria helpers
# --------------------------------------------------------------------------- #

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


def _safe_make_polygon(coords: List[Tuple[float, float]]) -> Optional[Any]:
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


def _buffer_node_as_polygon(lat: float, lon: float, radius_m: float) -> Optional[Any]:
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


# --------------------------------------------------------------------------- #
# Normalização (chave do seu problema)
# --------------------------------------------------------------------------- #

# landuse=* -> classes alvo do seu join
_LANDUSE_TO_CLASS = {
    "residential": "residential",
    "house": "residential",

    "commercial": "commercial",
    "retail": "commercial",

    "industrial": "industrial",
    "construction": "industrial",   # opcional: pode deixar "unknown" se preferir conservador
    "brownfield": "industrial",
    "quarry": "industrial",
}

_RES_BUILDINGS = {
    "house", "apartments", "residential", "terrace", "semidetached_house",
    "bungalow", "detached", "dormitory",
}
_COM_BUILDINGS = {
    "commercial", "retail", "office", "supermarket", "kiosk",
}
_IND_BUILDINGS = {
    "industrial", "warehouse", "factory", "manufacture",
}


def _normalize_from_tags(tags: Dict[str, Any]) -> str:
    t: Dict[str, str] = {}
    for k, v in (tags or {}).items():
        try:
            t[str(k)] = str(v)
        except Exception:
            continue

    # 1) Se tem landuse, prioriza (é o mais “territorial”)
    lu = (t.get("landuse") or "").strip().lower()
    if lu:
        return _LANDUSE_TO_CLASS.get(lu, "unknown")

    # 2) Infra/industrial forte (subestação etc)
    p = (t.get("power") or "").strip().lower()
    if p in {"substation", "plant", "generator"}:
        return "industrial"
    if (t.get("man_made") or "").strip().lower() == "works":
        return "industrial"
    if "industrial" in t:
        return "industrial"

    # 3) building=*
    b = (t.get("building") or "").strip().lower()
    if b in _IND_BUILDINGS:
        return "industrial"
    if b in _COM_BUILDINGS:
        return "commercial"
    if b in _RES_BUILDINGS:
        return "residential"

    # 4) POIs
    if "shop" in t or "office" in t:
        return "commercial"
    if "amenity" in t:
        return "commercial"

    return "unknown"


def _count_classes(polygons: List[Dict[str, Any]]) -> Dict[str, int]:
    c = {"residential": 0, "commercial": 0, "industrial": 0, "unknown": 0}
    for p in polygons or []:
        k = str(p.get("landuse", "unknown"))
        if k not in c:
            k = "unknown"
        c[k] += 1
    return c


# --------------------------------------------------------------------------- #
# Parsers
# --------------------------------------------------------------------------- #

def parse_polygons_landuse(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extrai polígonos de landuse=* e NORMALIZA para res/com/ind/unknown
    """
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
    """
    Fallback: buildings + POIs -> NORMALIZA p/ res/com/ind/unknown
    """
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

        # ways/relations -> polygon
        coords = _coords_from_geometry(el.get("geometry"))
        if coords:
            poly = _safe_make_polygon(coords)
            if poly is not None:
                polygons.append({"geometry": poly, "landuse": cls})
                continue

        # nodes -> buffer polygon
        if el.get("type") == "node" and "lat" in el and "lon" in el:
            poly = _buffer_node_as_polygon(float(el["lat"]), float(el["lon"]), float(poi_buffer_m))
            if poly is not None:
                polygons.append({"geometry": poly, "landuse": cls})

    return polygons


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def obter_poligonos_osm(lat: float, lon: float, raio_m: float) -> Dict[str, Any]:
    """
    - sucesso -> {"polygons": [...], "success": True}
    - falha   -> {"polygons": [], "success": False, "error": "..."}
    """
    logger.info("OSM | consulta iniciada (raio=%.0fm)", float(raio_m))

    try:
        # 1) landuse normalizado
        data = _post_overpass(_build_overpass_query_landuse(lat, lon, raio_m))
        polygons = parse_polygons_landuse(data)

        counts = _count_classes(polygons)
        classified = counts["residential"] + counts["commercial"] + counts["industrial"]
        logger.info(
            "OSM | landuse normalizado | total=%d | res=%d com=%d ind=%d unk=%d",
            len(polygons), counts["residential"], counts["commercial"], counts["industrial"], counts["unknown"]
        )

        # 2) fallback se classe útil ficou baixa
        if classified < MIN_CLASSIFIED_POLYGONS:
            logger.info(
                "OSM | classes úteis baixas (%d < %d) -> fallback buildings/POIs",
                classified, MIN_CLASSIFIED_POLYGONS
            )
            data_fb = _post_overpass(_build_overpass_query_fallback(lat, lon, raio_m))
            fb_polys = parse_polygons_fallback(data_fb, poi_buffer_m=POI_BUFFER_M)

            fb_counts = _count_classes(fb_polys)
            fb_classified = fb_counts["residential"] + fb_counts["commercial"] + fb_counts["industrial"]
            logger.info(
                "OSM | fallback ok | total=%d | res=%d com=%d ind=%d unk=%d",
                len(fb_polys), fb_counts["residential"], fb_counts["commercial"], fb_counts["industrial"], fb_counts["unknown"]
            )

            if MERGE_FALLBACK:
                polygons = polygons + fb_polys
                merged = _count_classes(polygons)
                logger.info(
                    "OSM | merge final | total=%d | res=%d com=%d ind=%d unk=%d",
                    len(polygons), merged["residential"], merged["commercial"], merged["industrial"], merged["unknown"]
                )
            else:
                polygons = fb_polys

        logger.info("OSM | polígonos válidos=%d", len(polygons))
        return {"polygons": polygons, "success": True}

    except Exception as e:
        err = str(e)
        logger.warning("OSM | falhou: %s", err)
        return {"polygons": [], "success": False, "error": err}
