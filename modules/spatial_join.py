from __future__ import annotations
import logging
from shapely.geometry import Point, shape
from shapely.strtree import STRtree  # <--- A chave da performance

logger = logging.getLogger("solarscan.spatial")

_PRIORITY = {"industrial": 3, "commercial": 2, "residential": 1, "unknown": 0}

def spatial_join(
    detections: list[dict],
    polygons: list[dict],
    max_near_m: float = 60.0,
) -> list[dict]:
    """
    Faz join ponto->polígono usando R-Tree (STRtree) para performance O(log N).
    """
    if not detections:
        return []
    
    if not polygons:
        # Se não tem mapa, tudo é unknown
        return [{**d, "landuse": "unknown", "landuse_confidence": "NONE"} for d in detections]

    # 1. Preparar Geometrias e Índice Espacial
    # Mantemos uma lista paralela para recuperar os metadados (landuse) pelo índice
    poly_geoms = []
    poly_metadata = []
    
    for p in polygons:
        geom = p.get("geometry")
        if geom and geom.is_valid:
            poly_geoms.append(geom)
            poly_metadata.append(str(p.get("landuse", "unknown")))

    if not poly_geoms:
        return [{**d, "landuse": "unknown"} for d in detections]

    # Constrói a árvore uma única vez (Muito rápido)
    tree = STRtree(poly_geoms)

    result = []

    for det in detections:
        pt = Point(det["lon"], det["lat"])
        
        # 2. Query Otimizada: A árvore retorna apenas candidatos que intersectam ou estão muito perto
        # query(geometry) retorna índices dos polígonos que tocam o bounding box do ponto
        candidate_indices = tree.query(pt)
        
        best = "unknown"
        best_score = -1
        found_hit = False

        # Verifica interseção real apenas nos candidatos (poucos)
        for idx in candidate_indices:
            geom = poly_geoms[idx]
            if geom.contains(pt) or geom.intersects(pt):
                lu = poly_metadata[idx]
                score = _PRIORITY.get(lu, 0)
                if score > best_score:
                    best = lu
                    best_score = score
                    found_hit = True
        
        if found_hit:
            result.append({**det, "landuse": best, "landuse_confidence": "HIGH"})
            continue

        # 3. Fallback: Proximidade (Nearest Neighbor)
        # O STRtree também tem 'nearest', mas para manter a lógica original de 'max_near_m':
        # Buscamos vizinhos num buffer ao redor do ponto para não varrer o mapa todo
        query_buffer = pt.buffer(max_near_m / 111320.0) # Aprox metros para graus
        near_indices = tree.query(query_buffer)
        
        nearest_lu = "unknown"
        nearest_score = -1
        nearest_dist_m = float("inf")

        for idx in near_indices:
            geom = poly_geoms[idx]
            # Distância aproximada em graus convertida para metros
            # Nota: shapely distance é cartesiana plana, para lat/lon precisa de projeção ou aprox
            # Usando a aprox simples do seu código original:
            d_deg = geom.distance(pt)
            d_m = d_deg * 111320.0 

            if d_m <= max_near_m:
                lu = poly_metadata[idx]
                score = _PRIORITY.get(lu, 0)
                
                # Lógica de prioridade: Menor distância desempata maior prioridade
                if (score > nearest_score) or (score == nearest_score and d_m < nearest_dist_m):
                    nearest_score = score
                    nearest_lu = lu
                    nearest_dist_m = d_m

        if nearest_dist_m < float("inf") and nearest_score > 0:
            result.append({
                **det, 
                "landuse": nearest_lu, 
                "landuse_confidence": "LOW", 
                "landuse_near_m": round(nearest_dist_m, 1)
            })
        else:
            result.append({**det, "landuse": "unknown", "landuse_confidence": "NONE"})

    return result

def aggregate_landuse(joined: list[dict]) -> dict:
    summary = {}
    for item in joined or []:
        k = str(item.get("landuse", "unknown"))
        summary[k] = summary.get(k, 0) + 1
    return summary