"""
MÓDULO 5 — osm.py
Contextualização territorial via OpenStreetMap (OSM)

Responsabilidade:
- Consultar Overpass API
- Retornar polígonos de uso do solo normalizados

Formato de retorno (compatível com spatial_join.py):
[
  {"geometry": shapely.geometry.Polygon, "landuse": "residential|commercial|industrial|..."},
  ...
]
"""

from __future__ import annotations

import os
import time
import logging
from typing import Any, Dict, List, Optional

import requests
import certifi
from requests.exceptions import RequestException, SSLError

from shapely.geometry import Polygon
from shapely.validation import make_valid


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

# Pode setar no .env:
# OVERPASS_URL=https://overpass.kumi.systems/api/interpreter
_overpass_env = "https://overpass.kumi.systems/api/interpreter"

OVERPASS_ENDPOINTS: List[str] = [
    _overpass_env,
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.nchc.org.tw/api/interpreter",
]
OVERPASS_ENDPOINTS = [u for u in OVERPASS_ENDPOINTS if u]  # remove vazios


# --------------------------------------------------------------------------- #
# Query builder
# --------------------------------------------------------------------------- #

def _build_overpass_query(lat: float, lon: float, raio_m: float) -> str:
    """
    Query para buscar polígonos de landuse no raio (metros).
    Retorna geometria para construir Polygon via shapely.
    """
    r = int(max(1.0, float(raio_m)))

    return f"""
    [out:json][timeout:25];
    (
      way["landuse"](around:{r},{lat},{lon});
      relation["landuse"](around:{r},{lat},{lon});
    );
    out geom;
    """


# --------------------------------------------------------------------------- #
# Overpass request (robusto)
# --------------------------------------------------------------------------- #

def query_overpass(lat: float, lon: float, raio_m: float) -> Dict[str, Any]:
    """
    Faz POST no Overpass com:
    - verify SSL usando certifi
    - retries leves
    - fallback de endpoints

    Levanta RuntimeError se falhar em todos.
    """
    query = _build_overpass_query(lat, lon, raio_m)
    last_err: Optional[Exception] = None

    # retries por endpoint
    for url in OVERPASS_ENDPOINTS:
        for attempt in range(1, 4):
            try:
                logger.info("OSM | tentando endpoint=%s (tentativa %d/3)", url, attempt)

                resp = requests.post(
                    url,
                    data={"data": query},
                    headers={"User-Agent": "SolarScan/1.0 (requests)"},
                    timeout=(10, 60),  # connect, read
                    verify=certifi.where(),  # <- importante p/ evitar CA bundle velho/quebrado
                )
                resp.raise_for_status()

                # Overpass pode devolver HTML/erro; aqui garantimos JSON
                return resp.json()

            except SSLError as e:
                # SSL falhou: normalmente é proxy/CA/self-signed. Troca endpoint.
                last_err = e
                logger.warning("OSM | SSL falhou no endpoint=%s | %s", url, str(e))
                break

            except ValueError as e:
                # JSON inválido
                last_err = e
                logger.warning("OSM | JSON inválido endpoint=%s | %s", url, str(e))
                time.sleep(0.5 * attempt)

            except RequestException as e:
                # timeouts, 429, 5xx etc
                last_err = e
                logger.warning("OSM | request falhou endpoint=%s | %s", url, str(e))
                time.sleep(0.6 * attempt)

    raise RuntimeError(f"Overpass API error: {last_err}")


# --------------------------------------------------------------------------- #
# Parser -> polygons
# --------------------------------------------------------------------------- #

def _coords_from_geometry(geom_list: Any) -> Optional[List[tuple]]:
    """
    Converte geometry do Overpass em lista de coordenadas (lon, lat).
    Espera lista de dicts: [{"lat": ..., "lon": ...}, ...]
    """
    if not isinstance(geom_list, list) or len(geom_list) < 3:
        return None

    coords: List[tuple] = []
    for p in geom_list:
        if not isinstance(p, dict) or "lat" not in p or "lon" not in p:
            continue
        coords.append((float(p["lon"]), float(p["lat"])))

    if len(coords) < 3:
        return None

    # fecha o anel se necessário
    if coords[0] != coords[-1]:
        coords.append(coords[0])

    # ainda precisa ter pelo menos 4 pontos (inclui o fechamento)
    if len(coords) < 4:
        return None

    return coords


def parse_polygons(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extrai polígonos do JSON do Overpass.

    Retorna:
      [{"geometry": Polygon, "landuse": str}, ...]
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

        landuse = str(tags.get("landuse", "unknown")).strip() or "unknown"

        geom_list = el.get("geometry")
        coords = _coords_from_geometry(geom_list)
        if not coords:
            continue

        try:
            poly = Polygon(coords)
            if poly.is_empty:
                continue

            # Corrige polígonos inválidos (self-intersections etc)
            if not poly.is_valid:
                poly = make_valid(poly)

            # make_valid pode retornar GeometryCollection; tentamos manter Polygon-like
            if hasattr(poly, "geom_type") and poly.geom_type not in ("Polygon", "MultiPolygon"):
                continue

            polygons.append({"geometry": poly, "landuse": landuse})
        except Exception:
            # se um elemento vier quebrado, ignora e segue
            continue

    return polygons


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def obter_poligonos_osm(lat: float, lon: float, raio_m: float) -> Dict[str, Any]:
    """
    Interface segura pro pipeline:
    - sucesso -> {"polygons": [...], "success": True}
    - falha   -> {"polygons": [], "success": False, "error": "..."}
    """
    logger.info("OSM | consulta iniciada (raio=%.0fm)", float(raio_m))

    try:
        data = query_overpass(lat, lon, raio_m)
        polygons = parse_polygons(data)
        logger.info("OSM | polígonos válidos=%d", len(polygons))

        return {
            "polygons": polygons,
            "success": True,
        }

    except Exception as e:
        err = str(e)
        logger.warning("OSM | falhou: %s", err)

        return {
            "polygons": [],
            "success": False,
            "error": err,
        }
