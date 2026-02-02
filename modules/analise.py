"""
Módulo para análise de impacto da geração distribuída na rede elétrica.
"""

def analisar_impacto_rede(contagem_por_tipo: dict, total_paineis: int) -> dict:
    total = sum(contagem_por_tipo.values()) or 1

    percentuais = {
        k: round((contagem_por_tipo.get(k, 0) / total) * 100, 1)
        for k in ["residencial", "industrial", "comercial"]
    }

    # Risco Duck Curve
    pct_res = percentuais["residencial"]
    if pct_res > 60:
        risco_duck = "ALTO"
    elif pct_res > 30:
        risco_duck = "MODERADO"
    else:
        risco_duck = "BAIXO"

    # Penetração MMGD (heurística MVP)
    densidade = total_paineis / 100  # painéis / ha
    if densidade > 50:
        penetracao = "ALTA"
    elif densidade > 20:
        penetracao = "MÉDIA"
    else:
        penetracao = "BAIXA"

    return {
        "risco_duck_curve": risco_duck,
        "penetracao_mmgd": penetracao,
        "percentuais": percentuais,
        "recomendacoes": [
            "Monitorar fluxo reverso no período solar",
            "Avaliar reforço da subestação"
        ]
    }
