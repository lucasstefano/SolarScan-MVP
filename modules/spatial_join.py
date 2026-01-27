"""
Módulo para operações de Spatial Join.
"""

def fazer_spatial_join(deteccoes: list, poligonos: list) -> dict:
    """
    Associa cada detecção a um polígono de uso do solo.
    
    Args:
        deteccoes: Lista de detecções de painéis
        poligonos: Lista de polígonos de uso do solo
        
    Returns:
        dict: Contagem de painéis por tipo de uso do solo
    """
    # TODO: Implementar lógica real de spatial join
    print(f"[DEBUG] Executando spatial join entre {len(deteccoes)} detecções e {len(poligonos)} polígonos")
    
    # Mock: distribuição aleatória
    import random
    
    tipos = ["residencial", "industrial", "comercial", "desconhecido"]
    
    # Inicializar contadores
    contagem = {tipo: 0 for tipo in tipos}
    
    # Distribuir painéis aleatoriamente
    for _ in deteccoes:
        contagem[random.choice(tipos[:-1])] += 1  # exclui "desconhecido"
    
    return contagem