# pipeline.py
from __future__ import annotations

import os
import time
import logging
from pathlib import Path
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple, Union
from concurrent.futures import ThreadPoolExecutor, as_completed

from modules.imagens import baixar_imagem_tile
from modules.geo_calculos import gerar_grid_coordenadas, anexar_latlon_da_bbox

# YOLO (arquivo yolo.py na raiz do projeto)
from yolo import detectar_paineis_imagem

# Landuse + join + análise + output
from modules.landuse_provider import get_landuse_polygons
from modules.spatial_join import spatial_join, aggregate_landuse
from modules.analise import analisar_impacto_rede
from modules.saida import formatar_output

# serialização de polígonos (debug seguro)
try:
    from shapely.geometry import mapping
except Exception:
    mapping = None

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
        if x is None:
            return float(default)
        return float(x)
    except Exception:
        return float(default)

def _ensure_int(x, default: int) -> int:
    try:
        if x is None:
            return int(default)
        return int(x)
    except Exception:
        return int(default)

def _poligonos_para_json(poligonos: list) -> list:
    """
    Converte lista de polígonos (shapely) para formato serializável.

    - Se shapely+mapping disponível, converte geometry para GeoJSON-like.
    - Caso contrário, retorna só landuse (pra não quebrar json.dump).
    """
    out = []
    if not poligonos:
        return out

    for p in poligonos:
        if not isinstance(p, dict):
            continue

        lu = str(p.get("landuse", "unknown"))

        if mapping is not None and "geometry" in p:
            try:
                out.append({"landuse": lu, "geometry": mapping(p["geometry"])})
                continue
            except Exception:
                pass

        out.append({"landuse": lu})

    return out

def _get_bbox_xyxy(det: Dict[str, Any]) -> Optional[Tuple[float, float, float, float]]:
    """
    Normaliza bbox para (x1,y1,x2,y2) em pixels.
    Suporta formatos: bbox/xyxy/box=[x1,y1,x2,y2], x1..y2, xywh, x/y/width/height.
    """
    for k in ("bbox", "xyxy", "box"):
        v = det.get(k)
        if isinstance(v, (list, tuple)) and len(v) == 4:
            try:
                x1, y1, x2, y2 = map(float, v)
                return x1, y1, x2, y2
            except Exception:
                pass

    if all(k in det for k in ("x1", "y1", "x2", "y2")):
        try:
            return float(det["x1"]), float(det["y1"]), float(det["x2"]), float(det["y2"])
        except Exception:
            pass

    v = det.get("xywh")
    if isinstance(v, (list, tuple)) and len(v) == 4:
        try:
            cx, cy, w, h = map(float, v)
            return cx - (w / 2.0), cy - (h / 2.0), cx + (w / 2.0), cy + (h / 2.0)
        except Exception:
            pass

    if all(k in det for k in ("x", "y", "width", "height")):
        try:
            x = float(det["x"]); y = float(det["y"])
            w = float(det["width"]); h = float(det["height"])
            return x, y, x + w, y + h
        except Exception:
            pass

    return None

def _annotate_debug_image(raw_path: Path, detections: List[Dict[str, Any]], out_path: Path) -> bool:
    """
    Gera evidência visual:
    - Caixa (amarela) + label textual (RESIDENCIAL/COMERCIAL/INDUSTRIAL/UNKNOWN) acima da caixa.
    """
    if Image is None or ImageDraw is None:
        return False

    try:
        img = Image.open(str(raw_path)).convert("RGB")
        draw = ImageDraw.Draw(img)

        font = None
        if ImageFont is not None:
            try:
                font = ImageFont.load_default()
            except Exception:
                font = None

        for det in detections or []:
            bb = _get_bbox_xyxy(det)
            if bb is None:
                continue

            x1, y1, x2, y2 = bb
            draw.rectangle([x1, y1, x2, y2], outline="yellow", width=3)

            lu = str(det.get("landuse", "unknown")).upper()
            conf = str(det.get("landuse_confidence", "")).upper()
            label = lu if not conf else f"{lu} ({conf})"

            tx, ty = x1, max(0, y1 - 14)
            try:
                tw, th = draw.textsize(label, font=font)  # pillow <10
            except Exception:
                tw, th = (len(label) * 6, 12)

            draw.rectangle([tx, ty, tx + tw + 6, ty + th + 4], fill=(0, 0, 0))
            draw.text((tx + 3, ty + 2), label, fill="white", font=font)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(out_path))
        return True
    except Exception as e:
        logger.warning("Falha ao anotar imagem %s | %s", raw_path.name, str(e))
        return False


# -----------------------------------------------------------------------------
# Paralelo: processamento por tile
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
    """
    Processa 1 tile: baixa imagem, salva raw, roda YOLO, anexa metadados/latlon.
    Retorna: {"ok": bool, "detections": [...], "raw_path": str, "boxed_path": str, "det_sem_latlon": int}
    """
    try:
        img_bytes = baixar_imagem_tile(float(t_lat), float(t_lon), zoom=zoom, size=tile_size, scale=tile_scale)
        if not img_bytes:
            return {"ok": False, "detections": [], "raw_path": "", "boxed_path": "", "det_sem_latlon": 0, "error": "tile vazio"}

        base = f"{sub_id}_tile_{i}"
        raw_path = raw_dir / f"{base}.png"
        boxed_path = boxed_dir / f"{base}_boxed.png"
        raw_path.write_bytes(img_bytes)

        deteccoes = detectar_paineis_imagem(img_bytes) or []

        # tamanho real da imagem (pra conversão bbox->latlon)
        if Image is not None:
            try:
                img_w, img_h = Image.open(BytesIO(img_bytes)).size
            except Exception:
                img_w, img_h = 1280, 1280
        else:
            img_w, img_h = 1280, 1280

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
                ok = anexar_latlon_da_bbox(
                    d,
                    tile_lat=float(t_lat),
                    tile_lon=float(t_lon),
                    zoom=int(zoom),
                    img_w=int(img_w),
                    img_h=int(img_h),
                )
                if not ok:
                    d["lat"] = float(t_lat)
                    d["lon"] = float(t_lon)
                    d["geo_fallback"] = "tile_center"
                    det_sem_latlon += 1

        return {
            "ok": True,
            "detections": deteccoes,
            "raw_path": str(raw_path),
            "boxed_path": str(boxed_path),
            "det_sem_latlon": int(det_sem_latlon),
        }

    except Exception as e:
        return {"ok": False, "detections": [], "raw_path": "", "boxed_path": "", "det_sem_latlon": 0, "error": str(e)}


# -----------------------------------------------------------------------------
# Core pipeline
# -----------------------------------------------------------------------------

def _pipeline_core(sub_id: str, lat: float, lon: float, raio_m: float) -> dict:
    # zoom e tamanho do tile usados pelo baixar_imagem_tile (devem ficar consistentes com geo_calculos.anexar_latlon_da_bbox)
    zoom = _ensure_int(os.getenv("TILE_ZOOM", "20"), 20)
    tile_size = os.getenv("TILE_SIZE", "640x640")
    tile_scale = _ensure_int(os.getenv("TILE_SCALE", "2"), 2)

    # paralelismo
    max_workers = _ensure_int(os.getenv("MAX_WORKERS", "6"), 6)
    max_workers = max(1, min(32, max_workers))

    t0 = time.time()
    logger.info("-" * 55)
    logger.info("INICIO | sub=%s | lat=%.6f lon=%.6f | raio=%.2fm", sub_id, lat, lon, raio_m)

    # Pasta debug (com subpastas)
    debug_root = Path(os.getenv("DEBUG_DIR", "debug_imagens")).resolve()
    raw_dir = debug_root / "raw"
    boxed_dir = debug_root / "boxed"
    raw_dir.mkdir(parents=True, exist_ok=True)
    boxed_dir.mkdir(parents=True, exist_ok=True)
    logger.info("DEBUG_DIR | %s", str(debug_root))

    # [1/6] Grid
    logger.info("[1/6] Gerando grid...")
    tiles = gerar_grid_coordenadas(lat, lon, raio_m)
    logger.info("[1/6] Grid pronto | tiles=%d", len(tiles))

    # [2/6] Imagens + YOLO (PARALELO)
    logger.info("[2/6] Baixando imagens e rodando YOLO (paralelo=%d workers)...", max_workers)

    todas_deteccoes: List[Dict[str, Any]] = []
    tiles_ok = 0
    tiles_fail = 0
    det_sem_latlon_total = 0

    futures = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for i, (t_lat, t_lon) in enumerate(tiles, 1):
            futures.append(
                ex.submit(
                    _process_tile,
                    sub_id=sub_id,
                    i=int(i),
                    t_lat=float(t_lat),
                    t_lon=float(t_lon),
                    zoom=int(zoom),
                    tile_size=str(tile_size),
                    tile_scale=int(tile_scale),
                    raw_dir=raw_dir,
                    boxed_dir=boxed_dir,
                )
            )

        for fut in as_completed(futures):
            r = fut.result() or {}
            if r.get("ok"):
                tiles_ok += 1
                dets = r.get("detections") or []
                todas_deteccoes.extend(dets)
                det_sem_latlon_total += int(r.get("det_sem_latlon") or 0)
            else:
                tiles_fail += 1

    total_paineis = len(todas_deteccoes)
    if det_sem_latlon_total:
        logger.warning(
            "Aviso: %d detecções sem lat/lon vieram do YOLO; usando centro do tile (fallback).",
            det_sem_latlon_total
        )
    logger.info("[2/6] YOLO ok | tiles_ok=%d tiles_fail=%d | detec_total=%d", tiles_ok, tiles_fail, total_paineis)

    # [3/6] Landuse polygons (DATA.RIO/GeoJSON/OSM)
    logger.info("[3/6] Consultando uso do solo (provider inteligente)...")
    landuse_payload = get_landuse_polygons(lat, lon, raio_m)
    poligonos = (landuse_payload or {}).get("polygons") or []
    provider = (landuse_payload or {}).get("provider") or "UNKNOWN"
    region = (landuse_payload or {}).get("region") or "BR"
    logger.info("[3/6] Polígonos carregados | provider=%s region=%s total=%d", provider, region, len(poligonos))

    poligonos_serializaveis = _poligonos_para_json(poligonos)

    # [4/6] Spatial Join
    logger.info("[4/6] Cruzando dados (IA + Mapas)...")
    joined = spatial_join(todas_deteccoes, poligonos)
    contagem_landuse_en = aggregate_landuse(joined)

    contagem_por_tipo = {
        "residencial": int(contagem_landuse_en.get("residential", 0)),
        "comercial": int(contagem_landuse_en.get("commercial", 0)),
        "industrial": int(contagem_landuse_en.get("industrial", 0)),
    }

    logger.info(
        "[4/6] Join ok | residencial=%d comercial=%d industrial=%d (unknown=%d)",
        contagem_por_tipo["residencial"],
        contagem_por_tipo["comercial"],
        contagem_por_tipo["industrial"],
        int(contagem_landuse_en.get("unknown", 0)),
    )

    # Evidência visual (após o join)
    if total_paineis > 0:
        by_tile: Dict[str, List[Dict[str, Any]]] = {}
        for det in joined:
            raw_path = str(det.get("tile_img_raw") or "")
            if raw_path:
                by_tile.setdefault(raw_path, []).append(det)

        annotated = 0
        for raw_path_str, dets in by_tile.items():
            raw_path = Path(raw_path_str)
            out_path = Path(dets[0].get("tile_img_boxed") or (boxed_dir / (raw_path.stem + "_boxed.png")))
            if _annotate_debug_image(raw_path, dets, out_path):
                annotated += 1

        logger.info("[4/6] Debug visual | tiles anotados=%d", annotated)

    # [5/6] Impacto
    logger.info("[5/6] Analisando MMGD/Duck Curve (com estimativas de potência e carga)...")
    impacto = analisar_impacto_rede(contagem_por_tipo, total_paineis, joined=joined)
    logger.info(
        "[5/6] Impacto ok | duck=%s | mmgd=%s | gen_kw=%.1f | carga_kw=%.1f",
        impacto.get("risco_duck_curve"),
        impacto.get("penetracao_mmgd"),
        float((impacto.get("estimativas") or {}).get("geracao_kw") or 0.0),
        float((impacto.get("estimativas") or {}).get("carga_pico_kw") or 0.0),
    )

    # [6/6] Output final
    logger.info("[6/6] Gerando JSON final...")
    output = formatar_output(
        id_subestacao=sub_id,
        lat=lat,
        lon=lon,
        contagem_por_tipo=contagem_por_tipo,
        impacto=impacto,
        total_paineis=total_paineis,
    )

    elapsed = time.time() - t0
    logger.info(
        "FIM | sub=%s | tiles_ok=%d tiles_fail=%d | detec_total=%d | tempo=%.2fs",
        sub_id, tiles_ok, tiles_fail, total_paineis, elapsed
    )

    return {
        "id": sub_id,
        "lat": float(lat),
        "lon": float(lon),
        "raio_m": float(raio_m),

        "tiles": tiles,  # tuples viram listas no json.dump (ok)

        "deteccoes": todas_deteccoes,
        "poligonos": poligonos_serializaveis,
        "joined": joined,

        "contagem_por_tipo": contagem_por_tipo,
        "impacto": impacto,
        "output": output,

        "debug_dir": str(debug_root),
        "stats": {
            "tiles_total": len(tiles),
            "tiles_ok": int(tiles_ok),
            "tiles_fail": int(tiles_fail),
            "detec_total": int(total_paineis),
            "det_sem_latlon": int(det_sem_latlon_total),
            "tempo_s": round(float(elapsed), 2),
            "poligonos_total": int(len(poligonos)),
            "provider": provider,
            "region": region,
            "max_workers": int(max_workers),
        },
    }


# -----------------------------------------------------------------------------
# API pública (compatível com chamadas antigas + novas)
# -----------------------------------------------------------------------------

def pipeline_solar_scan(*args, **kwargs) -> dict:
    """
    Aceita 3 jeitos de chamar (compatibilidade total):

    1) pipeline_solar_scan(dados_subestacao: dict, raio_calculado: float)
       - dados_subestacao = {"id": "...", "lat": ..., "lon": ...}

    2) pipeline_solar_scan(lat: float, lon: float, raio_m: float)
       - sub_id vira "SUB"

    3) pipeline_solar_scan(sub_id: str, lat: float, lon: float, raio_m: float)

    Se vier errado, lança erro com mensagem clara.
    """
    # kwargs (opcional)
    if kwargs:
        # permite: pipeline_solar_scan(sub_id="X", lat=..., lon=..., raio_m=...)
        if {"lat", "lon", "raio_m"}.issubset(kwargs.keys()):
            sub_id = str(kwargs.get("sub_id") or "SUB")
            lat = _ensure_float(kwargs.get("lat"), 0.0)
            lon = _ensure_float(kwargs.get("lon"), 0.0)
            raio_m = _ensure_float(kwargs.get("raio_m"), float(os.getenv("RAIO_PADRAO_METROS", "500.0")))
            return _pipeline_core(sub_id, lat, lon, raio_m)

    # formato 1: (dict, raio)
    if len(args) == 2 and isinstance(args[0], dict):
        dados_sub = args[0]
        raio_calc = args[1]
        sub_id = str(dados_sub.get("id") or "SUB")
        lat = _ensure_float(dados_sub.get("lat"), 0.0)
        lon = _ensure_float(dados_sub.get("lon"), 0.0)
        raio_m = _ensure_float(raio_calc, float(os.getenv("RAIO_PADRAO_METROS", "500.0")))
        return _pipeline_core(sub_id, lat, lon, raio_m)

    # formato 2: (lat, lon, raio)
    if len(args) == 3:
        lat = _ensure_float(args[0], 0.0)
        lon = _ensure_float(args[1], 0.0)
        raio_m = _ensure_float(args[2], float(os.getenv("RAIO_PADRAO_METROS", "500.0")))
        return _pipeline_core("SUB", lat, lon, raio_m)

    # formato 3: (sub_id, lat, lon, raio)
    if len(args) == 4:
        sub_id = str(args[0])
        lat = _ensure_float(args[1], 0.0)
        lon = _ensure_float(args[2], 0.0)
        raio_m = _ensure_float(args[3], float(os.getenv("RAIO_PADRAO_METROS", "500.0")))
        return _pipeline_core(sub_id, lat, lon, raio_m)

    raise TypeError(
        "Uso correto:\n"
        "  pipeline_solar_scan(dados_subestacao_dict, raio_calculado)\n"
        "  pipeline_solar_scan(lat, lon, raio_m)\n"
        "  pipeline_solar_scan(sub_id, lat, lon, raio_m)\n"
    )
