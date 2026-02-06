"""
Módulo para análise de impacto da geração distribuída na rede elétrica.
Utiliza Densidade de Carga (W/m²) para estimativa robusta.
"""
from __future__ import annotations
import math
from typing import Any, Dict, List, Optional
from modules.geo_calculos import meters_per_pixel_webmercator

# --- CONSTANTES DE ENGENHARIA (DENSIDADE DE CARGA) ---
# Valores típicos de mercado (PRODIST/Normas de Distribuição)
# Unidade: Watts por metro quadrado (W/m²)
DENSIDADE_CARGA_W_M2 = {
    "residencial": 25.0,  # Bairros classe média/alta ou densos
    "comercial": 60.0,    # Lojas, escritórios, shoppings (carga alta)
    "industrial": 45.0,   # Indústrias (média ponderada com pátios)
    "unknown": 15.0       # Áreas rurais ou pouco densas
}

# Fatores de Simultaneidade (Para não superestimar a carga de pico)
FATOR_SIMULTANEIDADE = 0.7 


# --- 1. Estimativa de Geração (REFATORADO) ---

def _bbox_area_m2(det: Dict[str, Any]) -> Optional[float]:
    """
    Calcula a área em m² de uma bbox.
    Espera formato padrão do YOLO: {'x', 'y', 'width', 'height'} (em pixels).
    """
    zoom = det.get("tile_zoom")
    lat = det.get("tile_lat")
    
    # Validação inicial limpa
    if zoom is None or lat is None:
        return None
    
    # CORREÇÃO LEGIBILIDADE: Prioriza formato padrão explícito
    bw, bh = 0.0, 0.0
    
    # 1. Tenta formato padrão (x, y, w, h)
    if all(k in det for k in ("width", "height")):
        bw = float(det["width"])
        bh = float(det["height"])
        
    # 2. Fallback para formato coordenadas (x1, y1, x2, y2) se necessário
    elif all(k in det for k in ("x1", "y1", "x2", "y2")):
        bw = float(det["x2"]) - float(det["x1"])
        bh = float(det["y2"]) - float(det["y1"])
        
    # 3. Fallback genérico para listas [x1, y1, x2, y2]
    elif "bbox" in det or "xyxy" in det:
        v = det.get("bbox") or det.get("xyxy")
        if isinstance(v, (list, tuple)) and len(v) == 4:
            x1, y1, x2, y2 = map(float, v)
            bw = x2 - x1
            bh = y2 - y1

    # Validação final de geometria
    if bw <= 0 or bh <= 0:
        return None

    mpp = meters_per_pixel_webmercator(float(lat), int(zoom))
    area = float(bw) * float(bh) * (mpp ** 2)
    
    # Filtro de sanidade (10 mil m2 é grande demais para 1 detecção residencial)
    return area if area < 10_000 else None 

def _estimate_kw_from_detection(det: Dict[str, Any], default_kw: float) -> float:
    lu = str(det.get("landuse") or "unknown").lower()
    area = _bbox_area_m2(det)
    
    if area is not None:
        dens = 0.18 # 180 Wp/m² (Painéis modernos)
        kw = area * dens
        kw = max(0.2, min(kw, 250.0))
    else:
        kw = float(default_kw)

    if "industr" in lu: kw *= 1.25
    elif "comerc" in lu: kw *= 1.10
    elif "resid" in lu: kw *= 0.95
    
    return float(kw)


# --- 2. Estimativa de Carga (ÁREA DENSIDADE) ---

def _estimar_carga_por_area(
    contagem_por_tipo: Dict[str, int], 
    raio_m: float
) -> float:
    """Calcula a carga da rede baseada na ÁREA TOTAL x DENSIDADE DE USO."""
    area_total_m2 = math.pi * (raio_m ** 2)
    
    total_samples = sum(contagem_por_tipo.values())
    
    if total_samples == 0:
        perc_res = 0.7; perc_com = 0.1; perc_ind = 0.0; perc_unk = 0.2
    else:
        perc_res = contagem_por_tipo.get("residencial", 0) / total_samples
        perc_com = contagem_por_tipo.get("comercial", 0) / total_samples
        perc_ind = contagem_por_tipo.get("industrial", 0) / total_samples
        perc_unk = max(0.0, 1.0 - (perc_res + perc_com + perc_ind))

    densidade_media = (
        (perc_res * DENSIDADE_CARGA_W_M2["residencial"]) +
        (perc_com * DENSIDADE_CARGA_W_M2["comercial"]) +
        (perc_ind * DENSIDADE_CARGA_W_M2["industrial"]) +
        (perc_unk * DENSIDADE_CARGA_W_M2["unknown"])
    )
    
    carga_total_w = area_total_m2 * densidade_media
    carga_total_kw = (carga_total_w / 1000.0) * FATOR_SIMULTANEIDADE
    
    return max(30.0, carga_total_kw)


def _classify_risk(pct_res: float, penetration: float) -> tuple[str, str]:
    if penetration >= 0.40: mmgd_risk = "CRÍTICA"
    elif penetration >= 0.20: mmgd_risk = "ALTA"
    elif penetration >= 0.10: mmgd_risk = "MÉDIA"
    else: mmgd_risk = "BAIXA"

    if pct_res > 60 and penetration > 0.15: duck_risk = "ALTO"
    elif pct_res > 40 and penetration > 0.10: duck_risk = "MODERADO"
    else: duck_risk = "BAIXO"
    
    return mmgd_risk, duck_risk

def analisar_impacto_rede(
    contagem_por_tipo: Dict[str, int],
    total_paineis: int,
    raio_analise_m: float,  
    joined: Optional[List[Dict[str, Any]]] = None,
    **kwargs
) -> Dict[str, Any]:
    
    if joined:
        gen_kw = sum(_estimate_kw_from_detection(d, 0.45) for d in joined)
    else:
        gen_kw = float(total_paineis) * 0.45

    peak_load_kw = _estimar_carga_por_area(contagem_por_tipo, raio_analise_m)
    
    penetration_ratio = gen_kw / peak_load_kw
    
    total_classificados = sum(contagem_por_tipo.values()) or 1
    pct_res = (contagem_por_tipo.get("residencial", 0) / total_classificados) * 100
    
    mmgd_risk, duck_risk = _classify_risk(pct_res, penetration_ratio)

    recs = []
    if mmgd_risk == "CRÍTICA":
        recs.append("ALTO RISCO DE INVERSÃO: Carga solar > 40% da demanda estimada.")
    if mmgd_risk == "ALTA":
        recs.append("Monitorar tensão no secundário (possível sobretensão).")
    if duck_risk == "ALTO":
        recs.append("Curva do Pato: Geração solar coincide com baixo consumo residencial.")

    return {
        "risco_duck_curve": duck_risk,
        "penetracao_mmgd": mmgd_risk,
        "percentuais": {
            "residencial": round(pct_res, 1),
            "industrial": round((contagem_por_tipo.get("industrial", 0)/total_classificados)*100, 1),
            "comercial": round((contagem_por_tipo.get("comercial", 0)/total_classificados)*100, 1)
        },
        "estimativas": {
            "geracao_solar_kwp": round(gen_kw, 1),
            "carga_rede_estimada_kw": round(peak_load_kw, 1),
            "area_analisada_m2": round(math.pi * (raio_analise_m**2), 0),
            "penetracao_ratio": round(penetration_ratio * 100, 2),
        },
        "recomendacoes": recs,
    }