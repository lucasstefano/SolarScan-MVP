from datetime import datetime, timezone
"""

from datetime import datetime, timezone
Módulo para formatação do output final.
"""

def formatar_output(id_subestacao: str, lat: float, lon: float,
                    contagem_por_tipo: dict, impacto: dict, 
                    total_paineis: int) -> dict:
    """
    Formata os dados no schema padrão da API SolarScan.
    
    Args:
        id_subestacao: ID da subestação
        lat: Latitude
        lon: Longitude
        contagem_por_tipo: Contagem de painéis por tipo
        impacto: Dicionário com análise de impacto
        total_paineis: Total de painéis detectados
        
    Returns:
        dict: Output formatado conforme especificação
    """
    # TODO: Ajustar para corresponder exatamente à especificação do documento
    
    # Determinar perfil predominante
    if total_paineis == 0:
        perfil_predominante = "INDEFINIDO"
    else:
        # Encontrar tipo com maior contagem
        perfil_predominante = max(contagem_por_tipo.items(), 
                                  key=lambda x: x[1])[0].upper()
    
    output = {
        "id_subestacao": id_subestacao,
        "latitude_sub": round(lat, 6),
        "longitude_sub": round(lon, 6),
        "perfil_predominante": perfil_predominante,
        "%_residencial": impacto.get("percentuais", {}).get("residencial", 0),
        "%_industrial": impacto.get("percentuais", {}).get("industrial", 0),
        "%_comercial": impacto.get("percentuais", {}).get("comercial", 0),
        "qnt_aprox_placa": total_paineis,
        "penetracao_mmgd": impacto.get("penetracao_mmgd", "INDEFINIDO"),
        "risco_duck_curve": impacto.get("risco_duck_curve", "INDEFINIDO"),
        "timestamp_processamento": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "versao_pipeline": "1.0.0-mvp"
    }
    
    return output