"""
Módulo para análise de impacto da geração distribuída na rede elétrica.

Upgrade (metodologia):
- Sai de "contagem pura" e passa a estimar potência (kW) com heurística:
  - Se a detecção tiver bbox + zoom + tamanho do tile => estima área (m²) e converte para kW
  - Caso contrário => usa kW médio por detecção (default)
- Cruza com heurísticas de carga (perfil residencial/comercial/industrial) para estimar penetração.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional


# -----------------------------
# Potência estimada (heurística)
# -----------------------------

def _meters_per_pixel_webmercator(lat: float, zoom: int) -> float:
    # WebMercator: metros por pixel em função de lat e zoom
    R = 6378137.0
    return (math.cos(math.radians(float(lat))) * 2.0 * math.pi * R) / (256.0 * (2.0 ** int(zoom)))


def _bbox_area_m2(det: Dict[str, Any]) -> Optional[float]:
    """
    Estima área (m²) do bbox com base em pixels e metros/pixel.

    Requer:
      - tile_zoom, tile_img_w, tile_img_h, tile_lat
      - bbox ou x/y/width/height (ou x1..y2)

    Obs: área de bbox é uma proxy — não representa área real de módulos,
    mas já dá ordem de grandeza para metodologia.
    """
    zoom = det.get("tile_zoom")
    lat = det.get("tile_lat")
    img_w = det.get("tile_img_w")
    img_h = det.get("tile_img_h")

    if zoom is None or lat is None or img_w is None or img_h is None:
        return None

    # bbox em px
    x1y1x2y2 = None
    for k in ("bbox", "xyxy", "box"):
        v = det.get(k)
        if isinstance(v, (list, tuple)) and len(v) == 4:
            try:
                x1, y1, x2, y2 = map(float, v)
                x1y1x2y2 = (x1, y1, x2, y2)
                break
            except Exception:
                pass

    if x1y1x2y2 is None and all(k in det for k in ("x1", "y1", "x2", "y2")):
        try:
            x1y1x2y2 = (float(det["x1"]), float(det["y1"]), float(det["x2"]), float(det["y2"]))
        except Exception:
            x1y1x2y2 = None

    if x1y1x2y2 is None and all(k in det for k in ("x", "y", "width", "height")):
        try:
            x = float(det["x"]); y = float(det["y"])
            w = float(det["width"]); h = float(det["height"])
            x1y1x2y2 = (x, y, x + w, y + h)
        except Exception:
            x1y1x2y2 = None

    if x1y1x2y2 is None:
        return None

    x1, y1, x2, y2 = x1y1x2y2
    bw = max(0.0, x2 - x1)
    bh = max(0.0, y2 - y1)
    if bw <= 0 or bh <= 0:
        return None

    mpp = _meters_per_pixel_webmercator(float(lat), int(zoom))
    area = float(bw) * float(bh) * (mpp ** 2)

    # limita outliers absurdos (bbox gigante)
    if area <= 0 or area > 10_000:
        return None
    return area


def _estimate_kw_from_detection(det: Dict[str, Any], default_kw: float) -> float:
    """
    Converte uma detecção em kW estimados.

    - Se tiver área m² => kW ≈ área_m2 * densidade_kW_m2 (proxy)
    - Ajuste por perfil (industrial/comercial pode ter arranjos mais densos)
    """
    lu = str(det.get("landuse") or "unknown").lower()

    # densidade média ~ 0.18 kW por m² (≈ 1 kW ~ 5.5 m²)
    # aplica um "cap" para não explodir em bbox ruim
    area = _bbox_area_m2(det)
    if area is not None:
        dens = 0.18
        kw = area * dens
        kw = max(0.1, min(kw, 50.0))  # 0.1kW..50kW por bbox
    else:
        kw = float(default_kw)

    # multiplicadores conservadores por uso
    if lu == "industrial":
        kw *= 1.30
    elif lu == "commercial":
        kw *= 1.10
    elif lu == "residential":
        kw *= 0.95

    return float(kw)


# -----------------------------
# Heurísticas de carga (proxy)
# -----------------------------

_LOAD_KW_PER_DET = {
    "residencial": 3.0,   # kW "equivalente" por detecção (proxy)
    "comercial": 15.0,
    "industrial": 40.0,
}

def _estimate_peak_load_kw(contagem_por_tipo: Dict[str, int]) -> float:
    res = float(contagem_por_tipo.get("residencial", 0)) * _LOAD_KW_PER_DET["residencial"]
    com = float(contagem_por_tipo.get("comercial", 0)) * _LOAD_KW_PER_DET["comercial"]
    ind = float(contagem_por_tipo.get("industrial", 0)) * _LOAD_KW_PER_DET["industrial"]

    base = res + com + ind
    # diversidade / margem (proxy para pico)
    return max(1.0, base * 1.4)


def _classify_penetration(ratio: float) -> str:
    if ratio >= 0.30:
        return "ALTA"
    if ratio >= 0.15:
        return "MÉDIA"
    return "BAIXA"


def _classify_duck_curve(pct_res: float, pen_ratio: float) -> str:
    # Duck curve é mais crítica quando:
    # - residencial domina e
    # - penetração é relevante
    if pct_res >= 60 and pen_ratio >= 0.20:
        return "ALTO"
    if pct_res >= 40 and pen_ratio >= 0.10:
        return "MODERADO"
    return "BAIXO"


# -----------------------------
# API principal
# -----------------------------

def analisar_impacto_rede(
    contagem_por_tipo: Dict[str, int],
    total_paineis: int,
    joined: Optional[List[Dict[str, Any]]] = None,
    default_kw_per_detection: float = 0.45,
) -> Dict[str, Any]:
    """
    Retorna:
      - percentuais por perfil
      - estimativas: geração_kw, carga_pico_kw, pen_ratio
      - classificações: penetracao_mmgd e risco_duck_curve
    """
    total = sum(contagem_por_tipo.values()) or 1

    percentuais = {
        k: round((float(contagem_por_tipo.get(k, 0)) / float(total)) * 100.0, 1)
        for k in ["residencial", "industrial", "comercial"]
    }

    # potência estimada (kW)
    if joined:
        gen_kw = sum(_estimate_kw_from_detection(d, default_kw_per_detection) for d in joined)
        kw_avg = (gen_kw / max(1, len(joined)))
    else:
        gen_kw = float(total_paineis) * float(default_kw_per_detection)
        kw_avg = float(default_kw_per_detection)

    # carga estimada (kW)
    peak_load_kw = _estimate_peak_load_kw(contagem_por_tipo)

    pen_ratio = float(gen_kw) / float(peak_load_kw) if peak_load_kw > 0 else 0.0
    penetracao = _classify_penetration(pen_ratio)

    pct_res = float(percentuais.get("residencial", 0.0))
    risco_duck = _classify_duck_curve(pct_res, pen_ratio)

    recomendacoes = []
    if penetracao != "BAIXA":
        recomendacoes.append("Avaliar fluxo reverso e tensão no período solar (meio do dia).")
    if risco_duck != "BAIXO":
        recomendacoes.append("Simular curva de carga (duck curve) e checar rampa no fim da tarde.")
    recomendacoes.append("Priorizar inspeção em clusters com alta densidade de geração estimada.")

    return {
        "risco_duck_curve": risco_duck,
        "penetracao_mmgd": penetracao,
        "percentuais": percentuais,
        "estimativas": {
            "geracao_kw": round(float(gen_kw), 1),
            "kw_medio_por_det": round(float(kw_avg), 2),
            "carga_pico_kw": round(float(peak_load_kw), 1),
            "penetracao_ratio": round(float(pen_ratio), 3),
        },
        "recomendacoes": recomendacoes,
    }
