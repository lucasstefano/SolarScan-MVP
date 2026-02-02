import numpy as np
import math
from sklearn.neighbors import NearestNeighbors

from config import (
    RAIO_MINIMO_METROS, 
    RAIO_MAXIMO_METROS, 
    RAIO_PADRAO_METROS,
    RAIO_TERRA_METROS
)
# Módulo para cálculos geoespaciais avançados
def calcular_raios_dinamicos(lista_subestacoes: list) -> dict:

    qtd = len(lista_subestacoes)
    resultado_raios = {}
    
    # CASO 1: Apenas 1 subestação (Sem vizinhos para comparar)
    if qtd < 2:
        print(" Apenas 1 subestação detectada. Usando raio padrão.")
        for sub in lista_subestacoes:
            resultado_raios[sub["id"]] = RAIO_PADRAO_METROS
        return resultado_raios

    # CASO 2: Múltiplas subestações (Cálculo Vetorial)
    print(f"Calculando densidade para {qtd} pontos...")

    # Extrair coordenadas e converter para Radianos (exigência do sklearn haversine)
    # Formato da matriz: [[lat_rad, lon_rad], [lat_rad, lon_rad], ...]
    coords_deg = np.array([[s['lat'], s['lon']] for s in lista_subestacoes])
    coords_rad = np.radians(coords_deg)

    # Configurar Modelo Nearest Neighbors
    # n_neighbors=2 porque o vizinho 1 é o próprio ponto (distância 0)
    vizinhos_proximos = NearestNeighbors(n_neighbors=2, algorithm='ball_tree', metric='haversine')
    vizinhos_proximos.fit(coords_rad)
    
    # Encontrar distâncias (retorna em radianos)
    distances_rad, indices = vizinhos_proximos.kneighbors(coords_rad)
    
    # O array distances_rad tem shape (N, 2). A coluna 0 é o próprio ponto, coluna 1 é o vizinho.
    vizinho_dist_rad = distances_rad[:, 1]
    
    # Converter radianos para metros
    vizinho_dist_metros = vizinho_dist_rad * RAIO_TERRA_METROS

    # Iterar e aplicar regras de negócio (Travas)
    for i, sub in enumerate(lista_subestacoes):
        dist_vizinho = vizinho_dist_metros[i]
        
        # Raio Calculado: Metade da distância ao vizinho mais próximo
        raio_calculado = dist_vizinho / 2.0
        
        # Aplicação das Travas (Clamping)
        if raio_calculado < RAIO_MINIMO_METROS:
            raio_final = RAIO_MINIMO_METROS
        elif raio_calculado > RAIO_MAXIMO_METROS:
            raio_final = RAIO_MAXIMO_METROS
        else:
            raio_final = raio_calculado
            
        resultado_raios[sub["id"]] = round(raio_final, 2)

    return resultado_raios

# Função para gerar uma grade de coordenadas cobrindo um círculo
def gerar_grid_coordenadas(lat: float, long: float, raio: float) -> list:

    # Converter metros para graus (aproximação na latitude)
    meters_per_degree = 111139.0   
    delta_lat = raio / meters_per_degree

    # Correção da longitude baseada na latitude (cos)
    cos_lat = math.cos(math.radians(lat))
    if abs(cos_lat) < 1e-12:
        cos_lat = 1e-12

    delta_lon = raio / (meters_per_degree * cos_lat)
    
    # Grid 3x3 simples cobrindo o ROI
    grade = []
    
    # Passo de varredura (step) - define sobreposição
    step_lat = delta_lat * 0.5
    step_lon = delta_lon * 0.5
    
    # Loop simples ao redor do centro
    for i in range(-1, 2):
        for j in range(-1, 2):
            lat_nova = lat + (i * step_lat)
            long_nova = long + (j * step_lon)
            grade.append((lat_nova, long_nova))
    i
    return grade