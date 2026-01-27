"""
Pipeline principal do SolarScan - orquestra todos os módulos.
"""

from modules.entrada import receber_requisicao
from modules.geo_calculos import calcular_raio_vizinho_mais_proximo, gerar_grid_coordenadas
from modules.imagens import baixar_imagem_tile
from modules.yolo import detectar_paineis_imagem
from modules.osm import obter_poligonos_osm
from modules.spatial_join import fazer_spatial_join
from modules.analise import analisar_impacto_rede
from modules.saida import formatar_output

def pipeline_solar_scan(json_input: dict) -> dict:
    """
    Orquestra todo o fluxo do SolarScan de forma sequencial.
    Retorna o output formatado conforme especificação técnica.
    """
    print("=" * 50)
    print("⚡ INICIANDO PIPELINE SOLARSCAN")
    print("=" * 50)
    
    # 1. Receber e validar entrada
    print("\n📥 [1/8] Recebendo entrada...")
    dados = receber_requisicao(json_input)
    print(f"   ✅ Dados validados: {dados['id']}")
    
    # 2. Calcular raio dinâmico
    print("\n📏 [2/8] Calculando raio de ação...")
    raio = calcular_raio_vizinho_mais_proximo(dados["lat"], dados["lon"])
    print(f"   ✅ Raio calculado: {raio:.2f}m")
    
    # 3. Gerar grid de coordenadas
    print("\n🗺️  [3/8] Gerando grid de coordenadas...")
    tiles = gerar_grid_coordenadas(dados["lat"], dados["lon"], raio)
    print(f"   ✅ Grid gerado: {len(tiles)} tiles")
    
    # 4. Processar cada tile (baixar imagem + detectar painéis)
    print("\n🛰️  [4/8] Processando imagens de satélite...")
    todas_deteccoes = []
    for i, tile in enumerate(tiles, 1):
        print(f"   🔄 Processando tile {i}/{len(tiles)}...")
        img_bytes = baixar_imagem_tile(tile[0], tile[1])
        deteccoes = detectar_paineis_imagem(img_bytes)
        todas_deteccoes.extend(deteccoes)
        print(f"     ✅ {len(deteccoes)} painéis detectados neste tile")
    
    total_paineis = len(todas_deteccoes)
    print(f"\n   📊 Total de painéis detectados: {total_paineis}")
    
    # 5. Obter dados do OpenStreetMap
    print("\n🏘️  [5/8] Obtendo dados de uso do solo (OSM)...")
    poligonos = obter_poligonos_osm(dados["lat"], dados["lon"], raio)
    print(f"   ✅ {len(poligonos)} polígonos obtidos")
    
    # 6. Spatial Join - associar detecções com polígonos
    print("\n🔗 [6/8] Executando Spatial Join...")
    contagem_por_tipo = fazer_spatial_join(todas_deteccoes, poligonos)
    print(f"   ✅ Distribuição: {contagem_por_tipo}")
    
    # 7. Análise de impacto na rede
    print("\n⚠️  [7/8] Analisando impacto na rede...")
    impacto = analisar_impacto_rede(contagem_por_tipo, total_paineis)
    print(f"   ✅ Análise concluída: {impacto.get('risco_duck_curve', 'N/A')}")
    
    # 8. Formatar saída final
    print("\n📋 [8/8] Formatando output final...")
    output = formatar_output(
        id_subestacao=dados["id"],
        lat=dados["lat"],
        lon=dados["lon"],
        contagem_por_tipo=contagem_por_tipo,
        impacto=impacto,
        total_paineis=total_paineis
    )
    
    print("\n" + "=" * 50)
    print("🎉 PIPELINE CONCLUÍDA COM SUCESSO!")
    print("=" * 50)
    
    return output