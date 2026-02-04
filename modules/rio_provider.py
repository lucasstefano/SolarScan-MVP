# modules/rio_provider.py
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from shapely.geometry import shape
from shapely.validation import make_valid

try:
    # Shapely 2.x
    from shapely.strtree import STRtree
except Exception:
    STRtree = None


@dataclass(frozen=True)
class PolygonRecord:
    geometry: Any  # shapely geometry
    landuse: str   # "residential|commercial|industrial|unknown"


# bbox aproximada do Município do Rio de Janeiro (WGS84, lon/lat)
RIO_BBOX = (-43.80, -23.10, -43.05, -22.75)  # (min_lon, min_lat, max_lon, max_lat)


def _safe_kind(x: Any) -> str:
    return str(x or "").strip().lower()

def map_rio_kind(properties: Dict[str, Any]) -> str:
    """
    Mapeamento EXATO baseado nos valores únicos do GeoJSON DATA.RIO (USO_DO_SOLO_2019).
    Corrige problemas onde áreas residenciais caiam em default/commercial.
    """
    p = properties or {}
    
    # Obtém o valor cru e normaliza (minusculo e sem espaços extras)
    # Ex: "Áreas residenciais" -> "áreas residenciais"
    uso_original = str(p.get("usoagregad") or "").strip().lower()
    
    # Dicionário de Mapeamento Direto (De -> Para)
    MAPPING = {
        # --- RESIDENCIAL ---
        "áreas residenciais": "residential",
        "favela": "residential",
        
        # --- COMERCIAL / SERVIÇOS / INSTITUCIONAL ---
        # Escolas, hospitais, shoppings, prédios públicos têm perfil de carga comercial
        "áreas de comércio e serviços": "commercial",
        "áreas de educação e saúde": "commercial",
        "áreas institucionais e de infraestrutura pública": "commercial",
        "áreas de lazer": "commercial", # Clubes, estádios, parques urbanos com edificações
        
        # --- INDUSTRIAL / INFRAESTRUTURA PESADA ---
        "áreas industriais": "industrial",
        "áreas de exploração mineral": "industrial", # Pedreiras
        "áreas de transporte": "industrial", # Portos, aeroportos, terminais de ônibus, garagens
        
        # --- DESCONHECIDO / NÃO URBANO (Ignorar na detecção ou tratar com cautela) ---
        "áreas não edificadas": "unknown", # Terrenos baldios (pode ter casa, mas oficial é vazio)
        "áreas agrícolas": "unknown",
        "afloramentos rochosos e depósitos sedimentares": "unknown",
        "cobertura arbórea e arbustiva": "unknown",
        "cobertura gramíneo lenhosa": "unknown",
        "corpos hídricos": "unknown",
        "áreas sujeitas à inundação": "unknown"
    }

    # 1. Tenta o match exato
    if uso_original in MAPPING:
        return MAPPING[uso_original]

    # 2. Fallback de segurança (caso apareça uma string nova no futuro)
    # Se contiver "residencial" ou "favela" no nome, força residencial
    if "residencial" in uso_original or "favela" in uso_original:
        return "residential"
    
    if "industrial" in uso_original or "indústria" in uso_original:
        return "industrial"

    # Se o grupo for "áreas urbanizadas" mas não sabemos o uso,
    # "unknown" é mais seguro que "commercial" para não enviesar a estatística
    grupo = str(p.get("grupo") or "").strip().lower()
    if "urbanizadas" in grupo:
        return "unknown" 

    return "unknown"


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


def _intersects_bbox(geom: Any, bbox: Tuple[float, float, float, float]) -> bool:
    try:
        minx, miny, maxx, maxy = bbox
        gx1, gy1, gx2, gy2 = geom.bounds
        return not (gx2 < minx or gx1 > maxx or gy2 < miny or gy1 > maxy)
    except Exception:
        return False


def _make_query_bbox(lat: float, lon: float, radius_m: float) -> Tuple[float, float, float, float]:
    import math
    dlat = float(radius_m) / 111_320.0
    dlon = float(radius_m) / (111_320.0 * max(1e-6, math.cos(math.radians(float(lat)))))
    return (float(lon) - dlon, float(lat) - dlat, float(lon) + dlon, float(lat) + dlat)


@lru_cache(maxsize=1)
def load_rio_polygons(path: str) -> Dict[str, Any]:
    """
    Carrega GeoJSON e retorna:
      {"records": [...], "index": STRtree|None, "geoms": [...]}
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"GeoJSON não encontrado: {p}")

    data = json.loads(p.read_text(encoding="utf-8"))
    feats = (data or {}).get("features", []) if isinstance(data, dict) else []
    if not isinstance(feats, list):
        feats = []

    records: List[PolygonRecord] = []
    geoms: List[Any] = []

    for f in feats:
        if not isinstance(f, dict):
            continue
        geom = _ensure_valid_geom(shape((f.get("geometry") or {})))
        if geom is None:
            continue

        props = f.get("properties") or {}
        kind = map_rio_kind(props)
        rec = PolygonRecord(geometry=geom, landuse=kind)
        records.append(rec)
        geoms.append(geom)

    idx = None
    if STRtree is not None and geoms:
        try:
            idx = STRtree(geoms)
        except Exception:
            idx = None

    return {"records": records, "index": idx, "geoms": geoms}


def query_rio_polygons(path: str, lat: float, lon: float, radius_m: float) -> List[Dict[str, Any]]:
    payload = load_rio_polygons(path)
    records: List[PolygonRecord] = payload["records"]
    idx = payload["index"]
    geoms = payload["geoms"]

    qbbox = _make_query_bbox(lat, lon, radius_m)

    candidate_idxs: List[int] = []

    if idx is not None and STRtree is not None:
        try:
            from shapely.geometry import box
            hits = idx.query(box(*qbbox))

            # ✅ Shapely pode retornar:
            # - lista/ndarray de índices (int)
            # - lista de geometrias
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

    # ✅ Se o índice falhar (ou retornar vazio), faz fallback pro scan bbox
    if not candidate_idxs:
        candidate_idxs = list(range(len(records)))

    out: List[Dict[str, Any]] = []
    for i in candidate_idxs:
        rec = records[i]
        if _intersects_bbox(rec.geometry, qbbox):
            out.append({"geometry": rec.geometry, "landuse": rec.landuse})

    return out


def is_inside_rio_bbox(lat: float, lon: float) -> bool:
    min_lon, min_lat, max_lon, max_lat = RIO_BBOX
    return (min_lat <= float(lat) <= max_lat) and (min_lon <= float(lon) <= max_lon)
