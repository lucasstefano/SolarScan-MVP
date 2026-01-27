"""
Módulo para aquisição de imagens de satélite.
"""

def baixar_imagem_tile(lat: float, lon: float, zoom: int = 18) -> bytes:
    """
    Baixa imagem de satélite do Google Maps Static API.
    
    Args:
        lat: Latitude do tile
        lon: Longitude do tile
        zoom: Nível de zoom (default 18)
        
    Returns:
        bytes: Imagem em formato bytes
    """
    # TODO: Implementar integração real com Google Maps API
    print(f"[DEBUG] Baixando imagem para ({lat:.6f}, {lon:.6f}) - zoom {zoom}")
    
    # Mock: retorna bytes vazios
    # Em produção, usar requests.get() com URL da API do Google
    return b"fake_image_data"