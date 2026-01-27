"""
Módulo para detecção de painéis solares usando YOLOv8.
"""

def detectar_paineis_imagem(imagem_bytes: bytes) -> list:
    """
    Executa inferência do YOLOv8 para detectar painéis solares.
    
    Args:
        imagem_bytes: Bytes da imagem
        
    Returns:
        list: Lista de detecções, cada uma com coordenadas e confiança
    """
    # TODO: Carregar modelo YOLOv8 real e executar inferência
    print("[DEBUG] Executando detecção YOLOv8...")
    
    # Mock: retorna detecções falsas
    import random
    
    num_deteccoes = random.randint(0, 5)  # 0 a 5 painéis por tile
    deteccoes = []
    
    for i in range(num_deteccoes):
        deteccoes.append({
            "x": random.randint(0, 640),
            "y": random.randint(0, 640),
            "width": random.randint(20, 100),
            "height": random.randint(20, 100),
            "confidence": random.uniform(0.7, 0.99),
            "class": "solar_panel"
        })
    
    return deteccoes