"""
Módulo para recepção e validação da entrada da API.
"""

def receber_requisicao(json_input: dict) -> dict:
    """
    Recebe e valida o JSON de entrada da API SolarScan.
    
    Args:
        json_input: Dicionário com id, lat, lon
        
    Returns:
        dict: Dados validados
        
    Raises:
        ValueError: Se a estrutura estiver incorreta
    """
    # TODO: Implementar validação completa
    required_keys = ["id", "lat", "lon"]
    
    for key in required_keys:
        if key not in json_input:
            raise ValueError(f"Campo obrigatório faltando: '{key}'")
    
    # Validar tipos
    if not isinstance(json_input["id"], str):
        raise ValueError("Campo 'id' deve ser string")
    
    if not (-90 <= json_input["lat"] <= 90):
        raise ValueError("Latitude fora do intervalo válido (-90 a 90)")
    
    if not (-180 <= json_input["lon"] <= 180):
        raise ValueError("Longitude fora do intervalo válido (-180 a 180)")
    
    print(f"[DEBUG] Entrada válida recebida para subestação: {json_input['id']}")
    return json_input