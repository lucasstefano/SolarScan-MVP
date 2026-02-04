# modules/landuse_provider.py
from __future__ import annotations

import json
import os
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from shapely.geometry import shape, box
from shapely.validation import make_valid

try:
    # Shapely 2.x
    from shapely.strtree import STRtree
except Exception:
    STRtree = None

from modules.rio_provider import is_inside_rio_bbox, query_rio_polygons
from modules.osm import obter_poligonos_osm

logger = logging.getLogger("solarscan.landuse")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", "%H:%M:%S"))
    logger.addHandler(h)
    logger.propagate = False

BASE_DIR = Path(__file__).resolve().parent.parent

# -----------------------------------------------------------------------------
# Region detection (lightweight, no external APIs)
# -----------------------------------------------------------------------------
# Obs: são bboxes aproximadas (estado inteiro). Servem só para escolher provider.
STATE_BBOX = {
    "RJ": (-44.9, -23.4, -40.8, -20.7),
    "SP": (-53.1, -25.5, -44.0, -19.6),
    "MG": (-51.3, -23.2, -39.8, -13.8),
}

def _inside_bbox(lat: float, lon: float, bbox: Tuple[float, float, float, float]) -> bool:
    min_lon, min_lat, max_lon, max_lat = bbox
    return (min_lat <= float(lat) <= max_lat) and (min_lon <= float(lon) <= max_lon)

def detect_region(lat: float, lon: float, region_hint: Optional[str] = None) -> Optional[str]:
    """
    Retorna: "RJ"|"SP"|"MG"|None
    region_hint (se informado) vence a heurística.
    """
    if region_hint:
        rh = str(region_hint).strip().upper()
        if rh in STATE_BBOX:
            return rh

    # RJ (município) tem detector mais preciso no rio_provider
    if is_inside_rio_bbox(lat, lon):
        return "RJ"

    for uf, bb in STATE_BBOX.items():
        if uf == "RJ":
            # RJ bbox amplo pode enganar; preferir o detector do município.
            continue
        if _inside_bbox(lat, lon, bb):
            return uf

    return None

# -----------------------------------------------------------------------------
# Generic GeoJSON provider (para SP/MG ou qualquer UF com GeoJSON local)
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class _GeoIndex:
    records: List[Dict[str, Any]]
    index: Any  # STRtree|None
    geoms: List[Any]

def _ensure_valid_geom(g: Any) -> Optional[Any]:
    try:
        if g is None or getattr(g, "is_empty", True):
            return None
        if not getattr(g, "is_valid", True):
            g = make_valid(g)
        gt = getattr(g, "geom_type", "")
        if gt not in ("Polygon", "MultiPolygon"):
            return None
        return g
    except Exception:
        return None

def _default_mapper(props: Dict[str, Any]) -> str:
    """
    Mapeamento genérico e conservador:
    - Se vier algo explicitamente classificado em propriedades, tenta usar.
    - Caso contrário: unknown.
    """
    p = props or {}
    # campos comuns em bases de uso do solo
    for key in ("landuse", "uso", "classe", "class", "tipo", "category", "categoria"):
        v = str(p.get(key) or "").strip().lower()
        if not v:
            continue
        if "res" in v or "morad" in v or "habita" in v:
            return "residential"
        if "ind" in v or "fabr" in v or "wareh" in v or "logist" in v:
            return "industrial"
        if "com" in v or "serv" in v or "shop" in v or "office" in v or "varej" in v:
            return "commercial"
    return "unknown"

@lru_cache(maxsize=8)
def _load_geojson_index(path: str, mapper_key: str) -> _GeoIndex:
    """
    Cacheia índices por path+mapper_key (mapper_key muda quando env/mapeamento muda).
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"GeoJSON não encontrado: {p}")

    data = json.loads(p.read_text(encoding="utf-8"))
    feats = (data or {}).get("features", []) if isinstance(data, dict) else []
    if not isinstance(feats, list):
        feats = []

    records: List[Dict[str, Any]] = []
    geoms: List[Any] = []

    mapper = _default_mapper  # hoje: genérico. (pode plugar mapper específico depois)

    for f in feats:
        if not isinstance(f, dict):
            continue
        geom = _ensure_valid_geom(shape((f.get("geometry") or {})))
        if geom is None:
            continue
        props = f.get("properties") or {}
        lu = mapper(props)
        records.append({"geometry": geom, "landuse": lu})
        geoms.append(geom)

    idx = None
    if STRtree is not None and geoms:
        try:
            idx = STRtree(geoms)
        except Exception:
            idx = None

    return _GeoIndex(records=records, index=idx, geoms=geoms)

def _make_query_bbox(lat: float, lon: float, radius_m: float) -> Tuple[float, float, float, float]:
    import math
    dlat = float(radius_m) / 111_320.0
    dlon = float(radius_m) / (111_320.0 * max(1e-6, math.cos(math.radians(float(lat)))))
    return (float(lon) - dlon, float(lat) - dlat, float(lon) + dlon, float(lat) + dlat)

def query_geojson_polygons(path: str, lat: float, lon: float, radius_m: float) -> List[Dict[str, Any]]:
    # mapper_key permite invalidar cache futuramente (ex: mapeamento custom por UF)
    mapper_key = "default"
    payload = _load_geojson_index(path, mapper_key)
    records = payload.records
    idx = payload.index
    geoms = payload.geoms

    qbbox = _make_query_bbox(lat, lon, radius_m)
    candidate_idxs: List[int] = []

    if idx is not None and STRtree is not None:
        try:
            hits = idx.query(box(*qbbox))
            if len(hits) > 0 and isinstance(hits[0], (int,)):
                candidate_idxs = [int(i) for i in hits]
            else:
                geom_to_i = {id(g): i for i, g in enumerate(geoms)}
                for g in hits:
                    i = geom_to_i.get(id(g))
                    if i is not None:
                        candidate_idxs.append(i)
        except Exception:
            candidate_idxs = []

    if not candidate_idxs:
        candidate_idxs = list(range(len(records)))

    out: List[Dict[str, Any]] = []
    for i in candidate_idxs:
        rec = records[i]
        try:
            # filtro rápido por bbox
            gx1, gy1, gx2, gy2 = rec["geometry"].bounds
            minx, miny, maxx, maxy = qbbox
            if gx2 < minx or gx1 > maxx or gy2 < miny or gy1 > maxy:
                continue
        except Exception:
            pass
        out.append(rec)

    return out

# -----------------------------------------------------------------------------
# Factory pattern: escolhe provider (RJ GeoJSON / UF GeoJSON / OSM)
# -----------------------------------------------------------------------------

def _env_path(primary: str, fallbacks: List[str], default: Optional[str] = None) -> str:
    """
    Pega a primeira env que existir + não vazia.
    """
    for k in [primary] + (fallbacks or []):
        v = os.getenv(k)
        if v and str(v).strip():
            return str(v).strip()
    return default or ""

DEFAULT_RIO_GEOJSON_PATH = _env_path(
    "RIO_USO_SOLO_GEOJSON",
    ["RIO_USO_GEOJSON"],
    str(BASE_DIR / "data" / "rio" / "USO_DO_SOLO_2019.geojson"),
)

DEFAULT_SP_GEOJSON_PATH = _env_path(
    "SP_USO_SOLO_GEOJSON",
    ["SP_USO_GEOJSON"],
    str(BASE_DIR / "data" / "sp" / "USO_SOLO_SP.geojson"),
)

DEFAULT_MG_GEOJSON_PATH = _env_path(
    "MG_USO_SOLO_GEOJSON",
    ["MG_USO_GEOJSON"],
    str(BASE_DIR / "data" / "mg" / "USO_SOLO_MG.geojson"),
)

def get_landuse_polygons(
    lat: float,
    lon: float,
    radius_m: float,
    region_hint: Optional[str] = None,
    rio_geojson_path: Optional[str] = None,
    sp_geojson_path: Optional[str] = None,
    mg_geojson_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Factory: detecta UF/região e escolhe provider.

    Cadeia:
      1) RJ (Município do Rio): DATA.RIO (GeoJSON local) se existir
      2) SP: GeoJSON local se existir
      3) MG: GeoJSON local se existir
      4) Fallback nacional: OSM melhorado
    """
    region = detect_region(lat, lon, region_hint=region_hint)

    # RJ (Município do Rio) - provider específico com mapping confiável
    if region == "RJ":
        rio_path = rio_geojson_path or DEFAULT_RIO_GEOJSON_PATH
        if Path(rio_path).exists():
            try:
                polys = query_rio_polygons(rio_path, lat, lon, radius_m) or []
                if polys:
                    return {"polygons": polys, "success": True, "provider": "DATA.RIO", "region": "RJ", "source_path": rio_path}

                osm = obter_poligonos_osm(lat, lon, radius_m)
                osm["provider"] = "OSM"
                osm["region"] = "RJ"
                osm["fallback_reason"] = "DATA.RIO vazio (sem match)"
                return osm
            except Exception as e:
                osm = obter_poligonos_osm(lat, lon, radius_m)
                osm["provider"] = "OSM"
                osm["region"] = "RJ"
                osm["fallback_reason"] = f"DATA.RIO falhou: {e}"
                return osm

        osm = obter_poligonos_osm(lat, lon, radius_m)
        osm["provider"] = "OSM"
        osm["region"] = "RJ"
        osm["fallback_reason"] = f"DATA.RIO ausente em {rio_path}"
        return osm

    # SP
    if region == "SP":
        sp_path = sp_geojson_path or DEFAULT_SP_GEOJSON_PATH
        if Path(sp_path).exists():
            try:
                polys = query_geojson_polygons(sp_path, lat, lon, radius_m) or []
                if polys:
                    return {"polygons": polys, "success": True, "provider": "GEOJSON_SP", "region": "SP", "source_path": sp_path}
            except Exception as e:
                logger.warning("SP provider falhou | %s", str(e))

    # MG
    if region == "MG":
        mg_path = mg_geojson_path or DEFAULT_MG_GEOJSON_PATH
        if Path(mg_path).exists():
            try:
                polys = query_geojson_polygons(mg_path, lat, lon, radius_m) or []
                if polys:
                    return {"polygons": polys, "success": True, "provider": "GEOJSON_MG", "region": "MG", "source_path": mg_path}
            except Exception as e:
                logger.warning("MG provider falhou | %s", str(e))

    # Nacional: OSM
    osm = obter_poligonos_osm(lat, lon, radius_m)
    osm["provider"] = "OSM"
    osm["region"] = region or "BR"
    if region in ("SP", "MG"):
        osm["fallback_reason"] = "GeoJSON estadual ausente/sem match"
    return osm
