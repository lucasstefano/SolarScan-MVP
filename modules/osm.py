"""
Módulo para integração com OpenStreetMap.
"""

def obter_poligonos_osm(lat: float, lon: float, raio: float) -> list:
    """
    Consulta OpenStreetMap para obter polígonos de uso do solo.
    
    Args:
        lat: Latitude central
        lon: Longitude central
        raio: Raio de busca em metros
        
    Returns:
        list: Lista de polígonos com metadata
    """
    # TODO: Implementar consulta real à Overpass API
    print(f"[DEBUG] Consultando OSM para área de {raio}m de raio")
    
    # Mock: retorna polígonos falsos
    import random
    
    tipos = ["residencial", "industrial", "comercial", "misto"]
    num_poligonos = random.randint(3, 8)
    
    poligonos = []
    for i in range(num_poligonos):
        poligonos.append({
            "id": f"poly_{i}",
            "tipo": random.choice(tipos),
            "area_m2": random.randint(500, 5000),
            "vertices": [
                [lat + random.uniform(-0.001, 0.001), 
                 lon + random.uniform(-0.001, 0.001)]
                for _ in range(4)
            ]
        })
    
    return poligonos