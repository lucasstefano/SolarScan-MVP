import json
import os

def processar_geojson():
    # 1. Pega o caminho da pasta onde este script (captura.py) está salvo
    diretorio_do_script = os.path.dirname(os.path.abspath(__file__))
    
    # 2. Cria o caminho completo para o arquivo geojson automaticamente
    # Isso evita erros se você rodar o script de outra pasta
    caminho_arquivo = os.path.join(diretorio_do_script, 'USO_DO_SOLO_2019.geojson')

    print(f"Lendo arquivo em: {caminho_arquivo}")

    try:
        with open(caminho_arquivo, 'r', encoding='utf-8') as f:
            data = json.load(f)

        resultados = set()
        
        # Lida tanto com FeatureCollection quanto com lista direta
        features = data.get('features') if 'features' in data else data

        for feature in features:
            props = feature.get('properties', {})
            
            # Pega os valores, usando "N/A" se o campo estiver vazio
            uso = props.get('usoagregad', 'N/A')
            grupo = props.get('grupo', 'N/A')
            
            # Adiciona ao conjunto (set) para remover repetições automaticamente
            resultados.add((uso, grupo))

        return resultados

    except FileNotFoundError:
        print("\nERRO: O arquivo ainda não foi encontrado.")
        print("Verifique se o nome 'USO_DO_SOLO_2019.geojson' está exato.")
        return set()
    except Exception as e:
        print(f"Ocorreu um erro: {e}")
        return set()

# Execução
unicos = processar_geojson()

if unicos:
    print("\n--- Valores Únicos Encontrados ---")
    print(f"{'USO AGREGADO'} | {'GRUPO'}")
    print("-" * 60)
    for uso, grupo in sorted(unicos):
        print(f"{str(uso)} | {str(grupo)}")
else:
    print("\nNenhum dado encontrado.")