# modules/landuse_provider.py
from __future__ import annotations

import json
import os
import logging
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from shapely.geometry import shape, box
from shapely.validation import make_valid

try:
    # Shapely 2.x
    from shapely.strtree import STRtree
except Exception:
    STRtree = None

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
# 1. Detecção de Região (Bounding Boxes Estaduais)
# -----------------------------------------------------------------------------
STATE_BBOXES = {
    "RJ": (-44.9, -23.4, -40.8, -20.7),
    "SP": (-53.1, -25.5, -44.0, -19.6),
    "MG": (-51.3, -23.2, -39.8, -13.8),
    "ES": (-41.9, -21.3, -39.6, -17.8),
    "BA": (-46.6, -18.4, -37.3, -8.5),
    "PR": (-54.6, -26.7, -48.0, -22.5),
    "SC": (-53.9, -29.4, -48.3, -25.9),
    "RS": (-57.7, -33.8, -49.6, -27.0),
}

def _inside_bbox(lat: float, lon: float, bbox: Tuple[float, float, float, float]) -> bool:
    min_lon, min_lat, max_lon, max_lat = bbox
    return (min_lat <= float(lat) <= max_lat) and (min_lon <= float(lon) <= max_lon)

def detect_region(lat: float, lon: float, region_hint: Optional[str] = None) -> Optional[str]:
    """Identifica a UF baseada na coordenada."""
    if region_hint:
        rh = str(region_hint).strip().upper()
        if rh in STATE_BBOXES:
            return rh

    for uf, bb in STATE_BBOXES.items():
        if _inside_bbox(lat, lon, bb):
            return uf

    return None


# -----------------------------------------------------------------------------
# 2. Motor de Leitura GeoJSON Genérico (Com Regras do RIO Padronizadas)
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

def _default_mapper(properties: Dict[str, Any]) -> str:
    """
    Mapeamento PADRONIZADO (Baseado no schema DATA.RIO).
    Assume que TODOS os GeoJSONs estaduais seguem a estrutura 'usoagregad' e 'grupo'.
    """
    p = properties or {}
    
    # 1. Obtém o valor cru do campo padrão (DATA.RIO)
    uso_original = str(p.get("usoagregad") or "").strip().lower()
    
    # 2. Dicionário de Mapeamento Direto (Lógica extraída do rio_provider.py)
    MAPPING = {
        # --- RESIDENCIAL ---
        "áreas residenciais": "residential",
        "favela": "residential",
        
        # --- COMERCIAL / SERVIÇOS / INSTITUCIONAL ---
        "áreas de comércio e serviços": "commercial",
        "áreas de educação e saúde": "commercial",
        "áreas institucionais e de infraestrutura pública": "commercial",
        "áreas de lazer": "commercial", 
        
        # --- INDUSTRIAL / INFRAESTRUTURA PESADA ---
        "áreas industriais": "industrial",
        "áreas de exploração mineral": "industrial",
        "áreas de transporte": "industrial",
        
        # --- DESCONHECIDO ---
        "áreas não edificadas": "unknown",
        "áreas agrícolas": "unknown",
        "afloramentos rochosos e depósitos sedimentares": "unknown",
        "cobertura arbórea e arbustiva": "unknown",
        "cobertura gramíneo lenhosa": "unknown",
        "corpos hídricos": "unknown",
        "áreas sujeitas à inundação": "unknown"
    }

    # 3. Tenta o match exato
    if uso_original in MAPPING:
        return MAPPING[uso_original]

    # 4. Heurísticas de Segurança (caso a string venha ligeiramente diferente)
    if "residencial" in uso_original or "favela" in uso_original:
        return "residential"
    
    if "industrial" in uso_original or "indústria" in uso_original:
        return "industrial"

    if "comércio" in uso_original or "serviço" in uso_original:
        return "commercial"

    # 5. Verifica o grupo (fallback do padrão Rio)
    grupo = str(p.get("grupo") or "").strip().lower()
    if "urbanizadas" in grupo:
        # Se for área urbanizada mas sem uso definido, 'unknown' é mais seguro
        return "unknown" 

    # 6. Último recurso: tenta campos genéricos caso o arquivo não siga o padrão estrito
    # (Mantido apenas para evitar que arquivos fora do padrão quebrem totalmente)
    # Mas a prioridade acima garante que se tiver 'usoagregad', ele manda.
    for key in ("landuse", "uso", "classe"):
        val = str(p.get(key) or "").lower()
        if "res" in val: return "residential"
        if "ind" in val: return "industrial"
        if "com" in val: return "commercial"

    return "unknown"

@lru_cache(maxsize=8)
def _load_geojson_index(path: str) -> _GeoIndex:
    """
    Carrega, valida e indexa o GeoJSON em memória.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {p}")

    logger.info(f"📂 Carregando GeoJSON padronizado: {p.name}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"Erro ao ler JSON {p}: {e}")
        return _GeoIndex([], None, [])

    feats = (data or {}).get("features", []) if isinstance(data, dict) else []
    
    records: List[Dict[str, Any]] = []
    geoms: List[Any] = []

    for f in feats:
        if not isinstance(f, dict): continue
        
        raw_geom = f.get("geometry")
        if not raw_geom: continue

        geom = _ensure_valid_geom(shape(raw_geom))
        if geom is None: continue

        props = f.get("properties") or {}
        # Usa o mapper padronizado (Rio Schema)
        lu = _default_mapper(props)
        
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
    dlat = float(radius_m) / 111_320.0
    cos_lat = max(1e-6, math.cos(math.radians(float(lat))))
    dlon = float(radius_m) / (111_320.0 * cos_lat)
    return (float(lon) - dlon, float(lat) - dlat, float(lon) + dlon, float(lat) + dlat)

def query_geojson_polygons(path: str, lat: float, lon: float, radius_m: float) -> List[Dict[str, Any]]:
    try:
        payload = _load_geojson_index(path)
    except FileNotFoundError:
        return []

    records = payload.records
    idx = payload.index
    geoms = payload.geoms
    
    if not records:
        return []

    qbbox = _make_query_bbox(lat, lon, radius_m)
    candidate_idxs: List[int] = []

    if idx is not None:
        try:
            hits = idx.query(box(*qbbox))
            if len(hits) > 0 and isinstance(hits[0], (int, int)): # type checking genérico para versões numpy
                 candidate_idxs = [int(i) for i in hits]
            else:
                geom_to_i = {id(g): i for i, g in enumerate(geoms)}
                for g in hits:
                    i = geom_to_i.get(id(g))
                    if i is not None: candidate_idxs.append(i)
        except Exception:
            candidate_idxs = []
    
    if not candidate_idxs and idx is None:
        candidate_idxs = list(range(len(records)))

    out: List[Dict[str, Any]] = []
    minx, miny, maxx, maxy = qbbox

    for i in candidate_idxs:
        rec = records[i]
        try:
            gx1, gy1, gx2, gy2 = rec["geometry"].bounds
            if gx2 < minx or gx1 > maxx or gy2 < miny or gy1 > maxy:
                continue
            out.append(rec)
        except Exception:
            pass

    return out


# -----------------------------------------------------------------------------
# 3. API Pública (Dynamic Dispatch)
# -----------------------------------------------------------------------------

def get_landuse_polygons(
    lat: float,
    lon: float,
    radius_m: float,
    region_hint: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    1. Detecta UF (ex: "SP").
    2. Busca: data/sp/landuse_SP.geojson
    3. Interpreta usando schema padrão (usoagregad/grupo).
    4. Fallback: OSM.
    """
    uf = detect_region(lat, lon, region_hint)
    
    polys = []
    fallback_reason = None
    
    if uf:
        uf_lower = uf.lower()
        uf_upper = uf.upper()
        
        expected_filename = f"landuse_{uf_upper}.geojson"
        dynamic_path = BASE_DIR / "data" / uf_lower / expected_filename
        
        if dynamic_path.exists():
            try:
                logger.info(f"📍 Região {uf} detectada. Buscando em: {dynamic_path}")
                polys = query_geojson_polygons(str(dynamic_path), lat, lon, radius_m)
                
                if polys:
                    return {
                        "polygons": polys,
                        "success": True,
                        "provider": f"GEOJSON_{uf_upper}",
                        "region": uf_upper,
                        "source_path": str(dynamic_path)
                    }
                else:
                    fallback_reason = f"Arquivo {expected_filename} lido mas sem polígonos na área"
            except Exception as e:
                logger.error(f"Erro ao ler GeoJSON de {uf}: {e}")
                fallback_reason = f"Erro leitura: {str(e)}"
        else:
            fallback_reason = f"Arquivo não encontrado: {dynamic_path}"
    else:
        fallback_reason = "Região não coberta por BBOXes estaduais"

    logger.info(f"🌐 Fallback para OSM. Motivo: {fallback_reason or 'Padrão'}")
    
    osm_data = obter_poligonos_osm(lat, lon, radius_m)
    osm_data["provider"] = "OSM"
    osm_data["region"] = uf or "BR"
    osm_data["fallback_reason"] = fallback_reason
    
    return osm_data