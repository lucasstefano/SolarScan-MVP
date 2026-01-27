"""
Módulo para cálculos geográficos e geração de grid.
"""

def calcular_raio_vizinho_mais_proximo(lat: float, lon: float) -> float:
    """
    Calcula o raio de ação usando a métrica do Vizinho Mais Próximo.
    
    Args:
        lat: Latitude da subestação
        lon: Longitude da subestação
        
    Returns:
        float: Raio em metros
    """
    # TODO: Implementar lógica real de Global Mean Nearest Neighbor
    # Por enquanto, retorna valores mock baseados na densidade
    print(f"[DEBUG] Calculando raio para coordenadas: ({lat}, {lon})")
    
    # Mock: retorna raio fixo para desenvolvimento
    return 1500.0  # 1.5km


def gerar_grid_coordenadas(lat: float, lon: float, raio: float) -> list:
    """
    Gera uma grade de coordenadas para cobrir a área circular.
    
    Args:
        lat: Latitude central
        lon: Longitude central
        raio: Raio em metros
        
    Returns:
        list: Lista de tuplas (lat, lon) para cada tile
    """
    # TODO: Implementar geração real de grid com sobreposição
    print(f"[DEBUG] Gerando grid para raio de {raio}m")
    
    # Mock: retorna apenas a coordenada central + 4 pontos ao redor
    import math
    
    # Converter graus para metros (aproximação)
    meters_per_degree = 111139
    
    delta_lat = raio / meters_per_degree
    delta_lon = raio / (meters_per_degree * math.cos(math.radians(lat)))
    
    # Grid simples 3x3
    grid = []
    for i in range(-1, 2):
        for j in range(-1, 2):
            new_lat = lat + i * delta_lat / 2
            new_lon = lon + j * delta_lon / 2
            grid.append((new_lat, new_lon))
    
    return grid