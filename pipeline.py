# pipeline_optimized.py
"""
Pipeline Otimizado com:
- YOLO singleton (modelo carrega 1x)
- Métricas agregadas de confiança
- Cache de imagens baixadas (opcional)
- Processamento paralelo otimizado
"""
from __future__ import annotations

import os
import time
import logging
import statistics
from pathlib import Path
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple, Union
from concurrent.futures import ThreadPoolExecutor, as_completed

from modules.imagens import baixar_imagem_tile
from modules.geo_calculos import (
    gerar_grid_coordenadas, 
    anexar_latlon_da_bbox, 
    filtrar_grid_com_mascara
)
from modules.osm import obter_mascara_edificacoes

# ⚡ IMPORT DO YOLO OTIMIZADO (use o arquivo novo)
from yolo import detectar_paineis_imagem

from modules.landuse_provider import get_landuse_polygons
from modules.spatial_join import spatial_join, aggregate_landuse
from modules.analise import analisar_impacto_rede
from modules.saida import formatar_output

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:
    Image = None
    ImageDraw = None
    ImageFont = None


logger = logging.getLogger("solarscan.pipeline")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", "%H:%M:%S"))
    logger.addHandler(handler)
    logger.propagate = False


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _ensure_float(x, default: float) -> float:
    try:
        return float(x) if x is not None else float(default)
    except Exception:
        return float(default)

def _ensure_int(x, default: int) -> int:
    try:
        return int(x) if x is not None else int(default)
    except Exception:
        return int(default)

def _annotate_debug_image(raw_path: Path, detections: List[Dict[str, Any]], out_path: Path) -> bool:
    if Image is None or ImageDraw is None:
        return False
    try:
        img = Image.open(str(raw_path)).convert("RGB")
        draw = ImageDraw.Draw(img)
        for det in detections or []:
            if all(k in det for k in ("x", "y", "width", "height")):
                x, y, w, h = det["x"], det["y"], det["width"], det["height"]
                x2, y2 = x + w, y + h
            else:
                continue

            draw.rectangle([x, y, x2, y2], outline="yellow", width=3)
        
        out_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(out_path))
        return True
    except Exception:
        return False


# -----------------------------------------------------------------------------
# 🔥 CACHE DE IMAGENS (Opcional - economiza chamadas de API)
# -----------------------------------------------------------------------------
_IMAGE_CACHE: Dict[str, bytes] = {}
_CACHE_ENABLED = os.getenv("IMAGE_CACHE", "true").lower() == "true"

def _get_cached_image(lat: float, lon: float, zoom: int, size: str, scale: int) -> Optional[bytes]:
    """Busca imagem no cache (se habilitado)"""
    if not _CACHE_ENABLED:
        return None
    
    key = f"{lat:.6f},{lon:.6f},z{zoom},{size},s{scale}"
    return _IMAGE_CACHE.get(key)

def _cache_image(lat: float, lon: float, zoom: int, size: str, scale: int, img_bytes: bytes):
    """Salva imagem no cache"""
    if not _CACHE_ENABLED or not img_bytes:
        return
    
    key = f"{lat:.6f},{lon:.6f},z{zoom},{size},s{scale}"
    _IMAGE_CACHE[key] = img_bytes
    
    # Limita tamanho do cache (max 100 imagens)
    if len(_IMAGE_CACHE) > 100:
        oldest_key = next(iter(_IMAGE_CACHE))
        del _IMAGE_CACHE[oldest_key]


# -----------------------------------------------------------------------------
# Paralelo: processamento por tile (OTIMIZADO)
# -----------------------------------------------------------------------------

def _process_tile(
    *,
    sub_id: str,
    i: int,
    t_lat: float,
    t_lon: float,
    zoom: int,
    tile_size: str,
    tile_scale: int,
    raw_dir: Path,
    boxed_dir: Path,
) -> Dict[str, Any]:
    try:
        # 🔥 Tenta cache primeiro
        img_bytes = _get_cached_image(t_lat, t_lon, zoom, tile_size, tile_scale)
        
        if img_bytes is None:
            img_bytes = baixar_imagem_tile(
                float(t_lat), float(t_lon), 
                zoom=zoom, size=tile_size, scale=tile_scale
            )
            if img_bytes:
                _cache_image(t_lat, t_lon, zoom, tile_size, tile_scale, img_bytes)
        
        if not img_bytes:
            return {
                "ok": False, 
                "detections": [], 
                "metrics": {},
                "raw_path": "", 
                "boxed_path": "", 
                "det_sem_latlon": 0
            }

        base = f"{sub_id}_tile_{i}"
        raw_path = raw_dir / f"{base}.png"
        boxed_path = boxed_dir / f"{base}_boxed.png"
        raw_path.write_bytes(img_bytes)

        # ⚡ YOLO OTIMIZADO (agora retorna métricas)
        deteccoes, metrics = detectar_paineis_imagem(img_bytes)

        # Calcula dimensões
        try:
            ts_w, ts_h = map(int, tile_size.split('x'))
            expected_w = ts_w * tile_scale
            expected_h = ts_h * tile_scale
        except Exception:
            expected_w, expected_h = 1280, 1280

        if Image is not None:
            try:
                img_w, img_h = Image.open(BytesIO(img_bytes)).size
            except Exception:
                img_w, img_h = expected_w, expected_h
        else:
            img_w, img_h = expected_w, expected_h

        det_sem_latlon = 0
        for d in deteccoes:
            d["tile_i"] = int(i)
            d["tile_lat"] = float(t_lat)
            d["tile_lon"] = float(t_lon)
            d["tile_zoom"] = int(zoom)
            d["tile_img_w"] = int(img_w)
            d["tile_img_h"] = int(img_h)
            d["tile_img_raw"] = str(raw_path)
            d["tile_img_boxed"] = str(boxed_path)

            if "lat" not in d or "lon" not in d:
                ok = anexar_latlon_da_bbox(d, float(t_lat), float(t_lon), int(zoom), int(img_w), int(img_h))
                if not ok:
                    d["lat"] = float(t_lat)
                    d["lon"] = float(t_lon)
                    d["geo_fallback"] = "tile_center"
                    det_sem_latlon += 1

        return {
            "ok": True,
            "detections": deteccoes,
            "metrics": metrics,  # 🔥 NOVO: métricas do YOLO
            "raw_path": str(raw_path),
            "boxed_path": str(boxed_path),
            "det_sem_latlon": int(det_sem_latlon),
        }

    except Exception as e:
        return {
            "ok": False, 
            "detections": [], 
            "metrics": {},
            "error": str(e)
        }


# -----------------------------------------------------------------------------
# 📊 AGREGADOR DE MÉTRICAS
# -----------------------------------------------------------------------------

def _aggregate_metrics(tile_metrics: List[Dict]) -> Dict[str, Any]:
    """Agrega métricas de todos os tiles"""
    if not tile_metrics:
        return {
            "total_tiles": 0,
            "total_detections": 0,
            "confidence_mean": 0.0,
            "confidence_min": 0.0,
            "confidence_max": 0.0,
            "avg_inference_time_ms": 0.0
        }
    
    all_confidences = []
    all_inference_times = []
    total_dets = 0
    
    for m in tile_metrics:
        if not m:
            continue
        total_dets += m.get("total_detections", 0)
        
        # Reconstrói lista de confianças (aproximado)
        mean = m.get("confidence_mean", 0)
        count = m.get("total_detections", 0)
        if mean > 0 and count > 0:
            all_confidences.extend([mean] * count)
        
        inf_time = m.get("inference_time_ms", 0)
        if inf_time > 0:
            all_inference_times.append(inf_time)
    
    return {
        "total_tiles": len(tile_metrics),
        "total_detections": total_dets,
        "confidence_mean": round(statistics.mean(all_confidences), 3) if all_confidences else 0.0,
        "confidence_min": round(min(all_confidences), 3) if all_confidences else 0.0,
        "confidence_max": round(max(all_confidences), 3) if all_confidences else 0.0,
        "confidence_std": round(statistics.stdev(all_confidences), 3) if len(all_confidences) > 1 else 0.0,
        "avg_inference_time_ms": round(statistics.mean(all_inference_times), 1) if all_inference_times else 0.0
    }


# -----------------------------------------------------------------------------
# Core pipeline (OTIMIZADO)
# -----------------------------------------------------------------------------

def _pipeline_core(sub_id: str, lat: float, lon: float, raio_m: float) -> dict:
    zoom = _ensure_int(os.getenv("TILE_ZOOM", "20"), 20)
    tile_size = os.getenv("TILE_SIZE", "640x640")
    tile_scale = _ensure_int(os.getenv("TILE_SCALE", "2"), 2)
    max_workers = _ensure_int(os.getenv("MAX_WORKERS", "6"), 6)
    osm_required = os.getenv("OSM_REQUIRED", "False").lower() == "true"

    t0 = time.time()
    logger.info("-" * 55)
    logger.info("INICIO | sub=%s | lat=%.6f lon=%.6f | raio=%.2fm | Zoom=%d", sub_id, lat, lon, raio_m, zoom)

    debug_root = Path(os.getenv("DEBUG_DIR", "debug_imagens")).resolve()
    raw_dir = debug_root / "raw"
    boxed_dir = debug_root / "boxed"
    raw_dir.mkdir(parents=True, exist_ok=True)
    boxed_dir.mkdir(parents=True, exist_ok=True)

    # [1/6] Grid
    logger.info("[1/6] Gerando grid ajustado para Zoom %d...", zoom)
    tiles = gerar_grid_coordenadas(lat, lon, raio_m, zoom=zoom)
    total_original = len(tiles)
    logger.info("[1/6] Grid BRUTO gerado | tiles=%d", total_original)

    # Smart Scan
    logger.info("🔍 [SMART SCAN] Baixando máscara de edificações do OSM...")
    mascara = obter_mascara_edificacoes(lat, lon, raio_m)
    
    if mascara:
        tiles = filtrar_grid_com_mascara(tiles, mascara, lat, zoom=zoom)
        total_filtrado = len(tiles)
        economia = total_original - total_filtrado
        perc_economia = (economia / total_original) * 100.0 if total_original > 0 else 0
        
        logger.info(f"💰 [SMART SCAN] Filtro Aplicado: {total_original} -> {total_filtrado} tiles.")
        logger.info(f"   📉 Economia de {perc_economia:.1f}% nas requisições da API.")
    else:
        if osm_required:
            error_msg = f"⛔ [SMART SCAN] ABORTANDO: OSM não retornou dados e OSM_REQUIRED=True."
            logger.error(error_msg)
            raise RuntimeError(error_msg)
        else:
            logger.warning("⚠️ [SMART SCAN] Nenhuma edificação encontrada. Usando grid completo (Custo $$$).")

    # [2/6] Imagens + YOLO (COM MÉTRICAS)
    logger.info("[2/6] Baixando imagens e rodando YOLO (paralelo=%d workers)...", max_workers)
    todas_deteccoes = []
    tile_metrics = []  # 🔥 NOVO
    tiles_ok = 0
    tiles_fail = 0

    futures = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for i, (t_lat, t_lon) in enumerate(tiles, 1):
            futures.append(ex.submit(
                _process_tile, 
                sub_id=sub_id, i=i, t_lat=t_lat, t_lon=t_lon, 
                zoom=zoom, tile_size=tile_size, tile_scale=tile_scale, 
                raw_dir=raw_dir, boxed_dir=boxed_dir
            ))

        for fut in as_completed(futures):
            r = fut.result() or {}
            if r.get("ok"):
                tiles_ok += 1
                todas_deteccoes.extend(r.get("detections") or [])
                tile_metrics.append(r.get("metrics", {}))  # 🔥 NOVO
            else:
                tiles_fail += 1

    total_paineis = len(todas_deteccoes)
    
    # 📊 AGREGA MÉTRICAS
    aggregated_metrics = _aggregate_metrics(tile_metrics)
    
    logger.info(
        "[2/6] YOLO ok | tiles_ok=%d tiles_fail=%d | detec_total=%d | conf_avg=%.3f", 
        tiles_ok, tiles_fail, total_paineis, aggregated_metrics.get("confidence_mean", 0.0)
    )

    # [3/6] Landuse
    logger.info("[3/6] Consultando uso do solo (provider inteligente)...")
    landuse_payload = get_landuse_polygons(lat, lon, raio_m)
    poligonos = (landuse_payload or {}).get("polygons") or []

    # [4/6] Spatial Join
    logger.info("[4/6] Cruzando dados (IA + Mapas)...")
    joined = spatial_join(todas_deteccoes, poligonos)
    contagem_landuse_en = aggregate_landuse(joined)
    contagem_por_tipo = {
        "residencial": int(contagem_landuse_en.get("residential", 0)),
        "comercial": int(contagem_landuse_en.get("commercial", 0)),
        "industrial": int(contagem_landuse_en.get("industrial", 0)),
    }

    if total_paineis > 0:
        by_tile = {}
        for det in joined:
            rp = str(det.get("tile_img_raw") or "")
            if rp: by_tile.setdefault(rp, []).append(det)
        for rp, dets in by_tile.items():
            _annotate_debug_image(Path(rp), dets, Path(dets[0].get("tile_img_boxed")))

    # [5/6] Impacto
    logger.info("[5/6] Analisando MMGD/Duck Curve (Densidade de Área)...")
    impacto = analisar_impacto_rede(
        contagem_por_tipo, 
        total_paineis, 
        raio_analise_m=raio_m,
        joined=joined
    )
    
    logger.info(
        "[5/6] Impacto ok | duck=%s | mmgd=%s | gen=%.1fkW | rede=%.1fkW",
        impacto.get("risco_duck_curve"),
        impacto.get("penetracao_mmgd"),
        float((impacto.get("estimativas") or {}).get("geracao_solar_kwp") or 0.0),
        float((impacto.get("estimativas") or {}).get("carga_rede_estimada_kw") or 0.0),
    )

    # [6/6] Output (COM MÉTRICAS)
    output = formatar_output(sub_id, lat, lon, contagem_por_tipo, impacto, total_paineis)
    
    # 🔥 ADICIONA MÉTRICAS DE YOLO NO OUTPUT
    output["yolo_metrics"] = aggregated_metrics
    
    elapsed = time.time() - t0
    logger.info("FIM | sub=%s | tempo=%.2fs", sub_id, elapsed)

    return {
        "id": sub_id,
        "output": output,
        "tiles": tiles,
        "deteccoes": todas_deteccoes,
        "joined": joined,
        "impacto": impacto,
        "yolo_metrics": aggregated_metrics  # 🔥 NOVO
    }


def pipeline_solar_scan(*args, **kwargs) -> dict:
    if kwargs:
        if {"lat", "lon"}.issubset(kwargs.keys()):
            return _pipeline_core(
                str(kwargs.get("sub_id") or "SUB"),
                _ensure_float(kwargs.get("lat"), 0.0),
                _ensure_float(kwargs.get("lon"), 0.0),
                _ensure_float(kwargs.get("raio_m"), 500.0)
            )
    
    if len(args) == 2 and isinstance(args[0], dict):
        return _pipeline_core(str(args[0].get("id")), float(args[0]["lat"]), float(args[0]["lon"]), float(args[1]))

    raise TypeError("Assinatura inválida para pipeline_solar_scan")