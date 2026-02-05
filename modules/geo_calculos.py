import numpy as np
import math
from typing import Any, Optional, Tuple, List, Dict
from sklearn.neighbors import NearestNeighbors

# --- OTIMIZAÇÃO: Usando STRtree em vez de unary_union ---
from shapely.geometry import box
from shapely.strtree import STRtree 
# --------------------------------------------------------

from config import (
    RAIO_MINIMO_METROS, 
    RAIO_MAXIMO_METROS, 
    RAIO_PADRAO_METROS,
    RAIO_TERRA_METROS
)

# -----------------------------------------------------------------------------
# Constantes Web Mercator
# -----------------------------------------------------------------------------
METERS_PER_DEGREE_LAT = 111139.0
_R_WEBMERCATOR = 6378137.0
_EQ_CIRCUMFERENCE = 2 * math.pi * _R_WEBMERCATOR  # ~40.075 km

def get_meters_per_pixel(lat: float, zoom: int) -> float:
    """Calcula resolução (metros reais no chão por pixel) para analise de área."""
    # Proteção de segurança contra polos
    lat = max(-85.05, min(85.05, lat))
    
    lat_rad = math.radians(lat)
    cos_lat = math.cos(lat_rad)
    if abs(cos_lat) < 1e-6: cos_lat = 1e-6
    world_pixels = 256.0 * (2.0 ** zoom)
    return (_EQ_CIRCUMFERENCE * cos_lat) / world_pixels

def meters_per_pixel_webmercator(lat: float, zoom: int) -> float:
    return get_meters_per_pixel(lat, zoom)

# -----------------------------------------------------------------------------
# 1. Lógica de Raios (KNN)
# -----------------------------------------------------------------------------
def calcular_raios_dinamicos(lista_subestacoes: list) -> dict:
    qtd = len(lista_subestacoes)
    resultado_raios = {}
    
    if qtd < 2:
        print("⚠ Apenas 1 subestação detectada. Usando raio padrão.")
        for sub in lista_subestacoes:
            resultado_raios[sub["id"]] = float(sub.get("raio_m", RAIO_PADRAO_METROS))
        return resultado_raios

    print(f"📐 Calculando densidade (KNN) para {qtd} pontos...")
    coords_deg = np.array([[s['lat'], s['lon']] for s in lista_subestacoes])
    coords_rad = np.radians(coords_deg)

    nbrs = NearestNeighbors(n_neighbors=2, algorithm='ball_tree', metric='haversine')
    nbrs.fit(coords_rad)
    distances_rad, _ = nbrs.kneighbors(coords_rad)
    dist_metros = distances_rad[:, 1] * RAIO_TERRA_METROS

    for i, sub in enumerate(lista_subestacoes):
        raio_calc = dist_metros[i] / 2.0
        raio_final = max(RAIO_MINIMO_METROS, min(raio_calc, RAIO_MAXIMO_METROS))
        resultado_raios[sub["id"]] = round(raio_final, 2)

    return resultado_raios

# -----------------------------------------------------------------------------
# 2. Geração de Grid (PIXEL PERFECT / ORDENADO NORTE -> SUL)
# -----------------------------------------------------------------------------
def _latlon_to_world_meters(lat: float, lon: float) -> Tuple[float, float]:
    """Converte Lat/Lon para Metros Projetados (EPSG:3857)."""
    lat = max(-85.05, min(85.05, lat)) # Clip de segurança
    mx = lon * _R_WEBMERCATOR * (math.pi / 180.0)
    my = math.log(math.tan((90 + lat) * math.pi / 360.0)) * _R_WEBMERCATOR
    return mx, my

def _world_meters_to_latlon(mx: float, my: float) -> Tuple[float, float]:
    """Converte Metros Projetados (EPSG:3857) para Lat/Lon."""
    lon = (mx / _R_WEBMERCATOR) * (180.0 / math.pi)
    lat = (math.atan(math.exp(my / _R_WEBMERCATOR)) * 360.0 / math.pi) - 90.0
    return lat, lon

def gerar_grid_coordenadas(lat: float, lon: float, raio: float, zoom: int = 20) -> List[Tuple[float, float]]:
    """
    Gera coordenadas centrais para tiles de 640x640px.
    Ordem: Cima para Baixo (Norte -> Sul), Esquerda para Direita (Oeste -> Leste).
    """
    IMG_SIZE_PX = 640.0
    
    # 1. Resolução PROJETADA
    resolution = _EQ_CIRCUMFERENCE / (256.0 * (2.0 ** zoom))
    tile_size_proj_m = IMG_SIZE_PX * resolution
    
    # 2. Converter centro da subestação
    center_mx, center_my = _latlon_to_world_meters(lat, lon)
    
    # 3. Calcular quantas tiles (Grid simétrico)
    scale_factor = 1.0 / math.cos(math.radians(max(-85, min(85, lat))))
    raio_proj = raio * scale_factor
    num_tiles_half = math.ceil(raio_proj / tile_size_proj_m)
    
    # 4. Gerar Grid Ordenado
    grade = []
    
    # Loop Norte -> Sul (Decrescente)
    for i in range(num_tiles_half, -num_tiles_half - 1, -1):
        for j in range(-num_tiles_half, num_tiles_half + 1):  # Oeste -> Leste
            
            # Calcula centro em metros projetados
            new_mx = center_mx + (j * tile_size_proj_m)
            new_my = center_my + (i * tile_size_proj_m) 
            
            n_lat, n_lon = _world_meters_to_latlon(new_mx, new_my)
            grade.append((n_lat, n_lon))
            
    return grade

# -----------------------------------------------------------------------------
# 3. Lógica Smart Scan (Filtro por Máscara OTIMIZADO COM R-TREE)
# -----------------------------------------------------------------------------
def filtrar_grid_com_mascara(
    grid: List[Tuple[float, float]], 
    poligonos_mask: List[Dict[str, Any]], 
    lat_centro: float,
    zoom: int = 19
) -> List[Tuple[float, float]]:
    """
    Recebe o grid completo e remove tiles que não interceptam nenhuma edificação.
    Usa Índice Espacial (STRtree) para performance O(log N).
    """
    if not poligonos_mask:
        return grid 

    # 1. Extrair geometrias válidas
    geoms = [p["geometry"] for p in poligonos_mask if "geometry" in p and p["geometry"].is_valid]
    
    if not geoms:
        return grid

    # 2. Criar Índice Espacial (R-Tree)
    # Isso é MUITO mais rápido que 'unary_union'
    tree = STRtree(geoms)

    # 3. Calcular box da Tile em Graus
    IMG_SIZE_PX = 640.0
    resolution = _EQ_CIRCUMFERENCE / (256.0 * (2.0 ** zoom))
    tile_size_m = IMG_SIZE_PX * resolution
    
    delta_lat = tile_size_m / METERS_PER_DEGREE_LAT
    cos_lat = math.cos(math.radians(max(-85, min(85, lat_centro))))
    if abs(cos_lat) < 1e-6: cos_lat = 1e-6
    delta_lon = tile_size_m / (METERS_PER_DEGREE_LAT * cos_lat)

    # Margem de segurança (10%)
    half_lat = (delta_lat * 1.1) / 2.0
    half_lon = (delta_lon * 1.1) / 2.0

    grid_filtrado = []
    for lat, lon in grid:
        tile_box = box(lon - half_lon, lat - half_lat, lon + half_lon, lat + half_lat)
        
        # 4. Busca Otimizada: A árvore diz se intercepta algo
        indices = tree.query(tile_box)
        if len(indices) > 0:
            grid_filtrado.append((lat, lon))

    return grid_filtrado

# -----------------------------------------------------------------------------
# 4. Helpers de Conversão (LatLon <-> Pixel)
# -----------------------------------------------------------------------------
def _mercator_from_latlon(lat: float, lon: float) -> Tuple[float, float]:
    lat = max(-85.05, min(85.05, lat))
    x = _R_WEBMERCATOR * math.radians(lon)
    y = _R_WEBMERCATOR * math.log(math.tan(math.pi / 4.0 + math.radians(lat) / 2.0))
    return x, y

def _latlon_from_mercator(x: float, y: float) -> Tuple[float, float]:
    lon = math.degrees(x / _R_WEBMERCATOR)
    lat = math.degrees(2.0 * math.atan(math.exp(y / _R_WEBMERCATOR)) - math.pi / 2.0)
    return lat, lon

def _bbox_center_px(det: Any) -> Optional[Tuple[float, float]]:
    if not isinstance(det, dict): return None
    if all(k in det for k in ("x", "y", "width", "height")):
        return det["x"] + (det["width"]/2), det["y"] + (det["height"]/2)
    for k in ("bbox", "xyxy", "box"):
        v = det.get(k)
        if isinstance(v, (list, tuple)) and len(v) == 4:
            return (v[0] + v[2])/2, (v[1] + v[3])/2
    return None

def anexar_latlon_da_bbox(det: dict, tile_lat: float, tile_lon: float, zoom: int, img_w: int, img_h: int) -> bool:
    c = _bbox_center_px(det)
    if c is None: return False

    cx, cy = c
    mpp = get_meters_per_pixel(tile_lat, zoom)

    dx = (cx - (img_w / 2.0)) * mpp
    dy = (cy - (img_h / 2.0)) * mpp

    x0, y0 = _mercator_from_latlon(tile_lat, tile_lon)
    lat, lon = _latlon_from_mercator(x0 + dx, y0 - dy)

    det["lat"] = float(lat)
    det["lon"] = float(lon)
    det["geo_fallback"] = "bbox_to_latlon"
    return True