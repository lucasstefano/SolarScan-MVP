"""
Módulo para análise de impacto na rede elétrica.
"""

def analisar_impacto_rede(contagem_por_tipo: dict, total_paineis: int) -> dict:
    """
    Analisa o impacto da GD na rede com base no perfil de uso do solo.
    
    Args:
        contagem_por_tipo: Dicionário com contagem por tipo
        total_paineis: Total de painéis detectados
        
    Returns:
        dict: Métricas de risco e impacto
    """
    # TODO: Implementar modelo real de análise de impacto
    print(f"[DEBUG] Analisando impacto para {total_paineis} painéis")
    
    # Calcular porcentagens
    total = sum(contagem_por_tipo.values())
    if total == 0:
        total = 1  # evitar divisão por zero
    
    pct_residencial = (contagem_por_tipo.get("residencial", 0) / total) * 100
    pct_industrial = (contagem_por_tipo.get("industrial", 0) / total) * 100
    pct_comercial = (contagem_por_tipo.get("comercial", 0) / total) * 100
    
    # Determinar risco de Duck Curve
    if pct_residencial > 60:
        risco_duck = "ALTO"
    elif pct_residencial > 30:
        risco_duck = "MODERADO"
    else:
        risco_duck = "BAIXO"
    
    # Calcular penetração MMGD (simplificado)
    densidade_paineis = total_paineis / 100  # painéis por hectare
    if densidade_paineis > 50:
        penetracao = "ALTA"
    elif densidade_paineis > 20:
        penetracao = "MÉDIA"
    else:
        penetracao = "BAIXA"
    
    return {
        "risco_duck_curve": risco_duck,
        "penetracao_mmgd": penetracao,
        "percentuais": {
            "residencial": round(pct_residencial, 1),
            "industrial": round(pct_industrial, 1),
            "comercial": round(pct_comercial, 1)
        },
        "recomendacoes": [
            "Monitorar fluxo reverso no período de pico solar",
            "Avaliar necessidade de reforço na subestação"
        ]
    }