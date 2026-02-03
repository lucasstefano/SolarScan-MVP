import json
import time
from modules.entrada import receber_requisicao
from modules.geo_calculos import calcular_raios_dinamicos
from pipeline import pipeline_solar_scan


def main() -> None:
    entrada_batch = [
        {"id": "SUB_BTF_CENTRO", "lat": -22.994598, "lon": -43.377366},
        {"id": "SUB_XYZ_VIZINHA", "lat": -22.999391, "lon": -43.431344},
        {"id": "SUB_RURAL_ISOLADA", "lat": -23.011251, "lon": -43.468282},
    ]

    print("🚀 INICIANDO SOLARSCAN (MODO BATCH)...")
    start_time = time.time()

    # 1) Validação
    try:
        dados_validos = receber_requisicao(entrada_batch)
    except ValueError as e:
        print(f"❌ Erro fatal na validação de entrada: {e}")
        return

    # 2) GEO: raios dinâmicos
    print("\n📐 [GEO] Calculando raios dinâmicos para otimização de custos...")
    try:
        mapa_de_raios = calcular_raios_dinamicos(dados_validos)
        if not isinstance(mapa_de_raios, dict):
            raise TypeError("calcular_raios_dinamicos deve retornar um dict {id: raio}.")
    except Exception as e:
        print(f"❌ Erro ao calcular raios dinâmicos: {e}")
        return

    print(f"   🔎 Raios definidos pelo algoritmo: {json.dumps(mapa_de_raios, indent=2, ensure_ascii=False)}")

    # 3) Pipeline
    outputs_finais = []
    debug_finais = []  # opcional: salva infos extras (sem shapely)

    print(f"\n🔄 Iniciando processamento sequencial de {len(dados_validos)} ativos...")

    for i, sub in enumerate(dados_validos, start=1):
        sub_id = sub["id"]
        raio_otimizado = mapa_de_raios.get(sub_id)

        if raio_otimizado is None:
            print(f"⚠️  [{i}/{len(dados_validos)}] {sub_id}: raio não encontrado no mapa. Usando fallback do pipeline.")
        else:
            print(f"✅ [{i}/{len(dados_validos)}] {sub_id}: raio_otimizado={raio_otimizado}")

        try:
            resultado = pipeline_solar_scan(sub, raio_otimizado)

            # ✅ SALVA SÓ O JSON FINAL (serializável)
            output = resultado.get("output")
            if not isinstance(output, dict):
                raise TypeError("pipeline_solar_scan deve retornar um dict com a chave 'output' (dict).")

            outputs_finais.append(output)

            # (opcional) debug SEM shapely: só métricas e contagens simples
            debug_finais.append({
                "id": sub_id,
                "tiles": resultado.get("tiles"),
                "deteccoes_total": resultado.get("deteccoes_total"),
                "det_sem_latlon": resultado.get("det_sem_latlon"),
                "contagem_por_tipo": resultado.get("contagem_por_tipo"),
                "impacto": resultado.get("impacto"),
            })

        except Exception as e:
            # Não quebra o batch inteiro — registra erro por ativo
            outputs_finais.append({
                "id_subestacao": sub_id,
                "latitude_sub": round(float(sub["lat"]), 6),
                "longitude_sub": round(float(sub["lon"]), 6),
                "erro": str(e),
                "versao_pipeline": "1.0.0-mvp",
            })

    # 4) Salvar (só JSON serializável)
    output_path = "resultado_solarscan_batch.json"
    print("\n💾 Salvando relatório consolidado...")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(outputs_finais, f, indent=2, ensure_ascii=False)

    # (opcional) arquivo de debug separado (também serializável)
    debug_path = "debug_solarscan_batch.json"
    with open(debug_path, "w", encoding="utf-8") as f:
        json.dump(debug_finais, f, indent=2, ensure_ascii=False)

    elapsed = time.time() - start_time
    print(f"\n🏁 Processo concluído em {elapsed:.2f} segundos!")
    print(f"✅ Resultados salvos em '{output_path}'")
    print(f"🧪 Debug salvo em '{debug_path}'")


if __name__ == "__main__":
    main()
