from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable, Dict, Any, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO

from PIL import Image

from modules.imagens import baixar_imagem_tile
from modules.geo_calculos import gerar_grid_coordenadas
from modules.geo_calculos import anexar_latlon_da_bbox  # opcional (se quiser lat/lon por det)

from yolo import detectar_paineis_imagem


def _ensure_int(v, default: int) -> int:
    try:
        return int(v)
    except Exception:
        return default


# ----------------------------
# Upgrade #1: prioridade centro -> bordas
# ----------------------------
def _sort_tiles_center_out(tiles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Ordena tiles para começar pelo centro (r1c1), depois cruz (dist 1),
    depois cantos (dist 2). Mantém determinístico.
    """
    def key(t):
        r, c = int(t["row"]), int(t["col"])
        manhattan = abs(r - 1) + abs(c - 1)
        # tie-break: primeiro mais ao norte (row menor), depois mais a oeste (col menor)
        return (manhattan, r, c)
    return sorted(tiles, key=key)


# ----------------------------
# Upgrade #2: deduplicação cross-tile (IoU) em coordenadas do mosaico
# ----------------------------
def _bbox_to_mosaic_pct(row: int, col: int, det: Dict[str, Any], img_w: int, img_h: int) -> Optional[Dict[str, float]]:
    """
    Converte bbox do tile para % no mosaico inteiro (0..100).
    Assume mosaico 3x3: cada tile ocupa 1/3 em largura e altura.
    """
    try:
        x = float(det["x"]); y = float(det["y"])
        w = float(det["width"]); h = float(det["height"])
        if img_w <= 0 or img_h <= 0:
            return None

        tile_left = (col / 3.0) * 100.0
        tile_top  = (row / 3.0) * 100.0

        left = tile_left + (x / img_w) * (100.0 / 3.0)
        top  = tile_top  + (y / img_h) * (100.0 / 3.0)
        width  = (w / img_w) * (100.0 / 3.0)
        height = (h / img_h) * (100.0 / 3.0)

        # clamp leve
        left = max(0.0, min(100.0, left))
        top = max(0.0, min(100.0, top))
        width = max(0.0, min(100.0 - left, width))
        height = max(0.0, min(100.0 - top, height))

        return {"left": left, "top": top, "width": width, "height": height}
    except Exception:
        return None


def _iou(a: Dict[str, float], b: Dict[str, float]) -> float:
    ax1, ay1 = a["left"], a["top"]
    ax2, ay2 = a["left"] + a["width"], a["top"] + a["height"]
    bx1, by1 = b["left"], b["top"]
    bx2, by2 = b["left"] + b["width"], b["top"] + b["height"]

    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)

    iw = max(0.0, inter_x2 - inter_x1)
    ih = max(0.0, inter_y2 - inter_y1)
    inter = iw * ih

    area_a = max(0.0, (ax2 - ax1)) * max(0.0, (ay2 - ay1))
    area_b = max(0.0, (bx2 - bx1)) * max(0.0, (by2 - by1))
    denom = area_a + area_b - inter
    if denom <= 0.0:
        return 0.0
    return inter / denom


class _GlobalDeduper:
    """
    Mantém uma lista de boxes aceitos em coordenadas do mosaico (%).
    Se um novo box sobrepõe acima do threshold, mantém o de maior conf.
    """
    def __init__(self, iou_thresh: float = 0.5):
        self.iou_thresh = float(iou_thresh)
        # cada item: {"id": str, "bbox": {left,top,width,height}, "conf": float}
        self.keep: List[Dict[str, Any]] = []
        self._counter = 0

    def add(self, bbox: Dict[str, float], conf: float) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Retorna:
          (accepted, replaced_item_or_None)
        - accepted=True: deve emitir pro front (novo ou substituiu um anterior)
        - replaced_item: se substituiu, retorna o item antigo (pra front remover pelo id)
        """
        conf = float(conf or 0.0)

        best_j = None
        best_iou = 0.0
        for j, it in enumerate(self.keep):
            v = _iou(bbox, it["bbox"])
            if v > best_iou:
                best_iou = v
                best_j = j

        if best_j is None or best_iou < self.iou_thresh:
            self._counter += 1
            new = {"id": f"det_{self._counter}", "bbox": bbox, "conf": conf}
            self.keep.append(new)
            return True, None

        # conflito: decide por conf
        existing = self.keep[best_j]
        if conf > float(existing["conf"]):
            self._counter += 1
            new = {"id": f"det_{self._counter}", "bbox": bbox, "conf": conf}
            self.keep[best_j] = new
            return True, existing

        return False, None


def _process_tile_raw_and_dets(
    *,
    sub_id: str,
    run_id: str,
    tile: Dict[str, Any],
    raw_dir: Path,
    zoom: int,
    tile_size: str,
    tile_scale: int,
) -> Dict[str, Any]:
    """
    1 tile:
      - baixa RAW
      - salva RAW
      - roda YOLO e retorna dets (x,y,w,h,confidence)
    """
    row = int(tile["row"])
    col = int(tile["col"])
    tile_i = int(tile["tile_i"])
    t_lat = float(tile["lat"])
    t_lon = float(tile["lon"])

    img_bytes = baixar_imagem_tile(float(t_lat), float(t_lon), zoom=zoom, size=tile_size, scale=tile_scale)
    if not img_bytes:
        return {"ok": False, "row": row, "col": col, "tile_i": tile_i, "error": "tile vazio"}

    raw_name = f"tile_r{row}_c{col}.png"
    raw_path = raw_dir / raw_name
    raw_path.write_bytes(img_bytes)

    try:
        img = Image.open(BytesIO(img_bytes))
        img_w, img_h = img.size
    except Exception:
        img_w, img_h = 1280, 1280

    dets = detectar_paineis_imagem(img_bytes) or []

    # opcional: adicionar lat/lon por detecção (best effort)
    for d in dets:
        d["tile_i"] = tile_i
        d["row"] = row
        d["col"] = col
        d["img_w"] = img_w
        d["img_h"] = img_h
        d["tile_lat"] = float(t_lat)
        d["tile_lon"] = float(t_lon)
        d["tile_zoom"] = int(zoom)
        try:
            anexar_latlon_da_bbox(d, float(t_lat), float(t_lon), int(zoom), int(img_w), int(img_h))
        except Exception:
            pass

    return {
        "ok": True,
        "row": row,
        "col": col,
        "tile_i": tile_i,
        "raw_name": raw_name,
        "img_w": img_w,
        "img_h": img_h,
        "dets": dets,
    }


def pipeline_stream_mosaico(
    sub: Dict[str, Any],
    raio_m: float,
    *,
    run_id: str,
    emit: Callable[[dict], None],
) -> Dict[str, Any]:
    """
    Pipeline streaming “mosaico RAW + overlay”
    Upgrade #1: prioridade centro->bordas
    Upgrade #2: dedup cross-tile com IoU em coords do mosaico
    """
    sub_id = str(sub.get("id") or "SUB")
    lat = float(sub["lat"])
    lon = float(sub["lon"])

    zoom = _ensure_int(os.getenv("TILE_ZOOM", "20"), 20)
    tile_size = os.getenv("TILE_SIZE", "640x640")
    tile_scale = _ensure_int(os.getenv("TILE_SCALE", "2"), 2)
    max_workers = max(1, min(16, _ensure_int(os.getenv("MAX_WORKERS", "6"), 6)))

    # debug por run/sub
    debug_root = Path(os.getenv("DEBUG_DIR", "debug_runs")).resolve()
    raw_dir = debug_root / run_id / sub_id / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    emit({
        "type": "sub_start",
        "run_id": run_id,
        "sub_id": sub_id,
        "lat": lat, "lon": lon,
        "raio_m": float(raio_m),
        "max_workers": int(max_workers),
    })

    tiles = gerar_grid_coordenadas(lat, lon, float(raio_m))
    tiles_ordered = _sort_tiles_center_out(tiles)

    emit({
        "type": "grid_ready",
        "run_id": run_id,
        "sub_id": sub_id,
        "tiles_total": len(tiles_ordered),
        "priority": "center_out",
    })

    t0 = time.time()
    done_count = 0
    det_emitted = 0

    # deduper global: reduz duplicados entre tiles vizinhos
    iou_thresh = float(os.getenv("DEDUP_IOU", "0.55"))
    deduper = _GlobalDeduper(iou_thresh=iou_thresh)

    futures = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        # Submit já em ordem de prioridade => o centro normalmente fica pronto primeiro.
        for tile in tiles_ordered:
            futures.append(ex.submit(
                _process_tile_raw_and_dets,
                sub_id=sub_id,
                run_id=run_id,
                tile=tile,
                raw_dir=raw_dir,
                zoom=zoom,
                tile_size=tile_size,
                tile_scale=tile_scale,
            ))

        for fut in as_completed(futures):
            r = fut.result() or {}
            done_count += 1

            if not r.get("ok"):
                emit({
                    "type": "tile_fail",
                    "run_id": run_id,
                    "sub_id": sub_id,
                    "row": r.get("row"), "col": r.get("col"), "tile_i": r.get("tile_i"),
                    "error": r.get("error", "erro"),
                })
            else:
                # tile_ready (RAW) — front coloca no mosaico pela posição
                emit({
                    "type": "tile_ready",
                    "run_id": run_id,
                    "sub_id": sub_id,
                    "row": r["row"], "col": r["col"], "tile_i": r["tile_i"],
                    "raw_name": r["raw_name"],
                    "img_w": r["img_w"], "img_h": r["img_h"],
                })

                # detecções — dedup global e emite como bbox no mosaico (%)
                dets = r.get("dets") or []
                for d in dets:
                    conf = float(d.get("confidence", 0.0) or 0.0)
                    bbox_pct = _bbox_to_mosaic_pct(int(r["row"]), int(r["col"]), d, int(r["img_w"]), int(r["img_h"]))
                    if not bbox_pct:
                        continue

                    accepted, replaced = deduper.add(bbox_pct, conf)
                    if not accepted:
                        continue

                    det_emitted += 1
                    emit({
                        "type": "det_add",
                        "run_id": run_id,
                        "sub_id": sub_id,
                        "det_id": None if replaced is None else replaced["id"],  # front pode remover o antigo
                        "new_det": {
                            "id": deduper.keep[-1]["id"] if replaced is None else None,  # id novo
                            "bbox_pct": bbox_pct,
                            "confidence": conf,
                            # extras opcionais
                            "tile_i": int(r["tile_i"]),
                            "row": int(r["row"]),
                            "col": int(r["col"]),
                            "lat": d.get("lat"),
                            "lon": d.get("lon"),
                        },
                        "replaced_id": replaced["id"] if replaced is not None else None,
                    })

            emit({
                "type": "progress",
                "run_id": run_id,
                "sub_id": sub_id,
                "done": done_count,
                "total": len(tiles_ordered),
                "pct": int((done_count / max(1, len(tiles_ordered))) * 100),
                "det_emitted": det_emitted,
            })

    elapsed = time.time() - t0

    result = {
        "id": sub_id,
        "lat": lat,
        "lon": lon,
        "raio_m": float(raio_m),
        "run_id": run_id,
        "stats": {
            "tiles_total": len(tiles_ordered),
            "det_emitted": det_emitted,
            "tempo_s": round(elapsed, 2),
            "dedup_iou": iou_thresh,
        }
    }

    emit({"type": "done", "run_id": run_id, "sub_id": sub_id, "result": result})
    return result
