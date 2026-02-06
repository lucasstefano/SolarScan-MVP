import json
import time
import os
import shutil
from pathlib import Path
from typing import List, Optional

# --- Imports da API ---
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv 

# --- Seus Imports (Mantenha a estrutura de pastas) ---
try:
    from modules.entrada import receber_requisicao
    from modules.geo_calculos import calcular_raios_dinamicos
    from pipeline import pipeline_solar_scan
except ImportError as e:
    print(f"⚠️ Erro de importação: {e}. Verifique se está rodando na raiz do projeto.")

# 1. Configuração de Ambiente
load_dotenv()
# Força carregamento do .env na mesma pasta (opcional)
env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)

# 2. Inicializa API
app = FastAPI(title="SolarScan Backend")

# 🔥 3. CONFIGURAÇÃO DO CORS (CRUCIAL PARA O FRONT END FUNCIONAR) 🔥
# Isso permite que seu localhost:5173 (React) chame o localhost:8000 (Python)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Em produção, troque "*" pela URL do seu front
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 4. Modelo de Dados (Exatamente como o Front End envia)
class ScanRequest(BaseModel):
    sub_id: str
    lat: float
    lon: float
    raio_m: float  # O Front envia 'raio_m'

# Função de limpeza
def limpar_debug():
    debug_path = Path("debug_imagens").resolve()
    if debug_path.exists():
        shutil.rmtree(debug_path, ignore_errors=True)

limpar_debug()

# ---------------------------------------------------------
# ROTA /scan (Compatível com SolarScanPage.tsx)
# ---------------------------------------------------------
@app.post("/scan")
async def processar_lote(requisicoes: List[ScanRequest]):
    """
    Recebe array: [{ sub_id, lat, lon, raio_m }, ...]
    Retorna: { results: [ ... ] }
    """
    print(f"\n🚀 [API] Recebida requisição com {len(requisicoes)} itens.")
    start_time = time.time()
    
    # Converter modelo Pydantic para o formato que seu pipeline antigo espera
    # O pipeline espera chaves "id", "lat", "lon". O front manda "sub_id".
    entrada_pipeline = []
    mapa_raios_manual = {} # Para guardar o raio que veio do front, se quiser forçar

    for req in requisicoes:
        item = {
            "id": req.sub_id,       # Mapeia sub_id -> id
            "lat": req.lat,
            "lon": req.lon
        }
        entrada_pipeline.append(item)
        # Se quiser usar o raio que veio do front, guardamos aqui:
        mapa_raios_manual[req.sub_id] = req.raio_m

    # 1) Validação
    try:
        dados_validos = receber_requisicao(entrada_pipeline)
    except ValueError as e:
        return {"ok": False, "error": str(e), "results": []}

    # 2) GEO: Raios dinâmicos (ou usa o do front se preferir)
    print("📐 [GEO] Calculando/Validando raios...")
    try:
        # Se quiser ignorar o cálculo e usar o input do front:
        # mapa_de_raios = mapa_raios_manual 
        
        # Ou usar o seu algoritmo inteligente (recomendado):
        mapa_de_raios = calcular_raios_dinamicos(dados_validos)
    except Exception as e:
        print(f"Erro GEO: {e}")
        # Fallback para o raio manual se o geo falhar
        mapa_de_raios = mapa_raios_manual

    # 3) Pipeline de Processamento
    outputs_finais = []
    
    print(f"🔄 Processando {len(dados_validos)} ativos...")

    for sub in dados_validos:
        sub_id = sub["id"]
        # Prioriza o raio calculado, senão usa o manual do front
        raio_otimizado = mapa_de_raios.get(sub_id, mapa_raios_manual.get(sub_id, 1000))

        item_result = {
            "ok": True,
            "data": None,
            "error": None
        }

        try:
            # Chama o pipeline original
            resultado = pipeline_solar_scan(sub, raio_otimizado)
            output = resultado.get("output")
            
            if output:
                # Garante que os campos batem com a interface do Front
                # O front espera: id_subestacao, latitude_sub, risco_duck_curve...
                item_result["data"] = output
            else:
                item_result["ok"] = False
                item_result["error"] = "Pipeline retornou vazio"

        except Exception as e:
            print(f"❌ Erro no item {sub_id}: {e}")
            item_result["ok"] = False
            item_result["error"] = str(e)
            
        outputs_finais.append(item_result)

    elapsed = time.time() - start_time
    print(f"✅ Concluído em {elapsed:.2f}s.")

    # Retorno no formato (A) que seu front suporta: { results: [...] }
    return {
        "results": outputs_finais
    }

if __name__ == "__main__":
    import uvicorn
    # Roda na porta 3000 (para bater com seu API_BASE) ou 8000
    print("🔋 API SolarScan Ativa.")
    uvicorn.run(app, host="127.0.0.1", port=8001)