from modules.geo_calculos import gerar_grid_coordenadas
from modules.imagens import baixar_imagem_tile
from yolo import detectar_paineis_imagem
from modules.osm import obter_poligonos_osm
from modules.spatial_join import fazer_spatial_join
from modules.analise import analisar_impacto_rede
from modules.saida import formatar_output

# MUDANÇA: Agora recebe o 'raio_calculado' como argumento obrigatório
def pipeline_solar_scan(dados_subestacao: dict, raio_calculado: float) -> dict:
    """
    Orquestra o fluxo para UMA subestação específica, usando o raio já definido.
    """
    sub_id = dados_subestacao["id"]
    lat = dados_subestacao["lat"]
    lon = dados_subestacao["lon"]

    print("\n" + "-" * 50)
    print(f"⚡ INICIANDO PROCESSAMENTO: {sub_id}")
    print(f"   📍 Coordenadas: {lat}, {lon}")
    print(f"   📏 Raio Definido (Dinâmico): {raio_calculado:.2f} metros")
    print("-" * 50)
    
    # OBS: O Passo 1 (Validação) e Passo 2 (Cálculo de Raio) agora acontecem fora daqui, no main.
    
    # 3. Gerar grid de coordenadas
    print(f"\n  [1/6] Gerando grid para raio {raio_calculado:.0f}m...")
    tiles = gerar_grid_coordenadas(lat, lon, raio_calculado)
    print(f"  Grid gerado: {len(tiles)} tiles para cobrir a área.")
    
    # 4. Processar cada tile (baixar imagem + detectar painéis)
    print("\n [2/6] Processando imagens de satélite...")
    todas_deteccoes = []
    
    for i, tile in enumerate(tiles, 1):
        # print(f"  Tile {i}/{len(tiles)}...") # Comentado para poluir menos o log
        img_bytes = baixar_imagem_tile(tile[0], tile[1])
        deteccoes = detectar_paineis_imagem(img_bytes)
        todas_deteccoes.extend(deteccoes)
    
    total_paineis = len(todas_deteccoes)
    print(f"  Total parcial: {total_paineis} painéis detectados na varredura.")
    
    # 5. Obter dados do OpenStreetMap
    print("\n [3/6] Obtendo contexto urbano (OSM)...")
    poligonos = obter_poligonos_osm(lat, lon, raio_calculado)
    print(f"   {len(poligonos)} polígonos de uso do solo encontrados.")
    
    # 6. Spatial Join - associar detecções com polígonos
    print("\n [4/6] Cruzando dados (IA + Mapas)...")
    contagem_por_tipo = fazer_spatial_join(todas_deteccoes, poligonos)
    
    # 7. Análise de impacto na rede
    print("\n [5/6] Analisando Duck Curve e riscos...")
    impacto = analisar_impacto_rede(contagem_por_tipo, total_paineis)
    
    # 8. Formatar saída final
    print("\n [6/6] Gerando JSON final...")
    output = formatar_output(
        id_subestacao=sub_id,
        lat=lat,
        lon=lon,
        contagem_por_tipo=contagem_por_tipo,
        impacto=impacto,
        total_paineis=total_paineis
    )
    
    return output