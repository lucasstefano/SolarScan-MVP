"""
Ponto de entrada principal para o MVP do SolarScan.
"""

from pipeline import pipeline_solar_scan
import json

def main():
    # Exemplo de entrada - mesma do documento
    entrada_exemplo = {
        "id": "SUB_BTF",
        "lat": -23.550520,
        "lon": -46.633308
    }
    
    print("🚀 Iniciando SolarScan MVP...")
    resultado = pipeline_solar_scan(entrada_exemplo)
    
    print("\n📊 Resultado do pipeline:")
    print(json.dumps(resultado, indent=2, ensure_ascii=False))
    
    # Salvar resultado em arquivo (para debug)
    with open("resultado_pipeline.json", "w", encoding="utf-8") as f:
        json.dump(resultado, f, indent=2, ensure_ascii=False)
    
    print("\n✅ Pipeline concluído! Resultado salvo em 'resultado_pipeline.json'")

if __name__ == "__main__":
    main()