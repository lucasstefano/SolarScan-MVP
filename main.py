import json
import time
import os
from dotenv import load_dotenv # Adicione esta linha
import shutil
# Garante que variáveis de ambiente estejam carregadas antes de qualquer import de módulo
load_dotenv() 

from modules.entrada import receber_requisicao
from modules.geo_calculos import calcular_raios_dinamicos
from pipeline import pipeline_solar_scan

from pathlib import Path

def limpar_debug_anterior():
    """
    Remove a pasta de debug antiga para evitar mistura de imagens de execuções passadas.
    """
    debug_path_str = os.getenv("DEBUG_DIR", "debug_imagens")
    debug_path = Path(debug_path_str).resolve()
    
    if debug_path.exists() and debug_path.is_dir():
        print(f"🧹 Limpando pasta de debug antiga: {debug_path}")
        try:
            shutil.rmtree(debug_path) # Deleta a pasta e tudo dentro dela
        except Exception as e:
            print(f"⚠️  Não foi possível limpar a pasta de debug: {e}")
    else:
        print(f"✨ Pasta de debug limpa (ou inexistente): {debug_path}")
# 1. Força o caminho exato onde o main.py está
caminho_env = Path(__file__).resolve().parent / ".env"

print(f"🔍 [DEBUG] Procurando .env em: {caminho_env}")
print(f"   Arquivo existe? {caminho_env.exists()}")

# 2. Carrega forçando esse caminho
load_dotenv(dotenv_path=caminho_env, override=True)

# 3. Testa se pegou a variável do Zoom (deveria ser 19)
print(f"   ZOOM Carregado: {os.getenv('TILE_ZOOM')} (Esperado: 19)")
print("-" * 30)

# ... resto dos imports (modules.entrada, etc) ...
def main() -> None:
    entrada_batch = [
        {"id": "SUB_BTF_CENTRO", "lat": -22.994598, "lon": -43.377366},
       
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
