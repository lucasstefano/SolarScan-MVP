import time
import logging
import os
from pathlib import Path
from modules.imagens import baixar_imagem_tile
from yolo import detectar_paineis_imagem, salvar_imagem_com_boxes

# NOVOS IMPORTS (OSM + join + análise + output)
from modules.osm import obter_poligonos_osm  # retorna {"polygons": [...], "success": True}  :contentReference[oaicite:2]{index=2}
from modules.spatial_join import spatial_join, aggregate_landuse  # :contentReference[oaicite:3]{index=3}
from modules.analise import analisar_impacto_rede  # :contentReference[oaicite:4]{index=4}
from modules.saida import formatar_output  # :contentReference[oaicite:5]{index=5}
from io import BytesIO

try:
    from PIL import Image
except Exception:
    Image = None

from modules.geo_calculos import gerar_grid_coordenadas, anexar_latlon_da_bbox


logger = logging.getLogger("solarscan.pipeline")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", "%H:%M:%S"))
    logger.addHandler(handler)
    logger.propagate = False


def pipeline_solar_scan(dados_subestacao: dict, raio_calculado: float) -> dict:
    sub_id = dados_subestacao["id"]
    lat = float(dados_subestacao["lat"])
    lon = float(dados_subestacao["lon"])

    t0 = time.time()
    logger.info("-" * 55)
    logger.info("INICIO | sub=%s | lat=%.6f lon=%.6f | raio=%.2fm", sub_id, lat, lon, raio_calculado)

    # Pasta debug (com subpastas)
    debug_root = Path(os.getenv("DEBUG_DIR", "debug_imagens")).resolve()
    raw_dir = debug_root / "raw"
    boxed_dir = debug_root / "boxed"
    raw_dir.mkdir(parents=True, exist_ok=True)
    boxed_dir.mkdir(parents=True, exist_ok=True)
    logger.info("DEBUG_DIR | %s", str(debug_root))

    # [1/6] Grid
    logger.info("[1/6] Gerando grid...")
    tiles = gerar_grid_coordenadas(lat, lon, raio_calculado)
    logger.info("[1/6] Grid pronto | tiles=%d", len(tiles))

    # [2/6] Imagens + YOLO
    logger.info("[2/6] Baixando imagens e rodando YOLO...")
    todas_deteccoes = []
    tiles_ok = 0
    tiles_fail = 0
    det_sem_latlon = 0

    for i, (t_lat, t_lon) in enumerate(tiles, 1):
        try:
            img_bytes = baixar_imagem_tile(t_lat, t_lon)
            if not img_bytes:
                tiles_fail += 1
                logger.warning("Tile %d/%d vazio | lat=%.6f lon=%.6f", i, len(tiles), t_lat, t_lon)
                continue

            base = f"{sub_id}_tile_{i}"
            raw_path = raw_dir / f"{base}.png"
            boxed_path = boxed_dir / f"{base}_boxed.png"

            # salva tile original
            raw_path.write_bytes(img_bytes)

            # detecta
            deteccoes = detectar_paineis_imagem(img_bytes) or []
            if Image is not None:
                try:
                    img_w, img_h = Image.open(BytesIO(img_bytes)).size
                except Exception:
                    img_w, img_h = 1280, 1280
            else:
                img_w, img_h = 1280, 1280

            # marca origem da detecção + garante lat/lon (pra spatial_join não quebrar)
            for d in deteccoes:
                d["tile_i"] = i
                d["tile_lat"] = float(t_lat)
                d["tile_lon"] = float(t_lon)
                d["tile_img_raw"] = str(raw_path)
                d["tile_img_boxed"] = str(boxed_path)

                if "lat" not in d or "lon" not in d:
                    ok = anexar_latlon_da_bbox(
                        d,
                        tile_lat=float(t_lat),
                        tile_lon=float(t_lon),
                        zoom=20,          # default do baixar_imagem_tile
                        img_w=int(img_w),
                        img_h=int(img_h),
                    )
                    if not ok:
                        d["lat"] = float(t_lat)
                        d["lon"] = float(t_lon)
                        d["geo_fallback"] = "tile_center"

            todas_deteccoes.extend(deteccoes)

            # salva versão com boxes (se quiser salvar sempre, remova o if)
            if deteccoes:
                salvar_imagem_com_boxes(img_bytes, deteccoes, boxed_path)
                logger.info("Tile %d/%d ok | detec=%d | boxed=%s", i, len(tiles), len(deteccoes), boxed_path.name)
            else:
                logger.info("Tile %d/%d ok | detec=0 | raw=%s", i, len(tiles), raw_path.name)

            tiles_ok += 1

        except Exception as e:
            tiles_fail += 1
            logger.warning("Tile %d/%d falhou | %s", i, len(tiles), str(e))

    total_paineis = len(todas_deteccoes)
    if det_sem_latlon:
        logger.warning(
            "Aviso: %d detecções sem lat/lon vieram do YOLO; usando centro do tile (fallback).",
            det_sem_latlon
        )

    # [3/6] OSM
    logger.info("[3/6] Obtendo contexto urbano (OSM)...")
    poligonos_resp = obter_poligonos_osm(lat, lon, raio_calculado)
    poligonos = (poligonos_resp or {}).get("polygons", [])
    logger.info("[3/6] OSM ok | poligonos=%d", len(poligonos))

    # [4/6] Spatial Join
    logger.info("[4/6] Cruzando dados (IA + Mapas)...")
    joined = spatial_join(todas_deteccoes, poligonos)
    contagem_landuse_en = aggregate_landuse(joined)

    # Mapeia para chaves PT que seus módulos esperam (residencial/comercial/industrial)
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

    # [5/6] Impacto
    logger.info("[5/6] Analisando Duck Curve e riscos...")
    impacto = analisar_impacto_rede(contagem_por_tipo, total_paineis)
    logger.info("[5/6] Impacto ok | duck=%s | mmgd=%s", impacto.get("risco_duck_curve"), impacto.get("penetracao_mmgd"))

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

    # Mantém seu retorno antigo + adiciona os novos artefatos
    return {
        "id": sub_id,
        "lat": lat,
        "lon": lon,
        "raio_m": float(raio_calculado),
        "tiles": tiles,
        "deteccoes": todas_deteccoes,
        "poligonos_osm": poligonos,              # polígonos shapely (debug)
        "joined": joined,                        # deteccoes + landuse (debug)
        "contagem_por_tipo": contagem_por_tipo,  # pt (para análise/output)
        "impacto": impacto,
        "output": output,                        # JSON final (o que você quer entregar)
        "debug_dir": str(debug_root),
        "stats": {
            "tiles_total": len(tiles),
            "tiles_ok": tiles_ok,
            "tiles_fail": tiles_fail,
            "detec_total": total_paineis,
            "det_sem_latlon": det_sem_latlon,
            "tempo_s": round(elapsed, 2),
            "poligonos_osm": len(poligonos),
        },
    }
