import math

def gerar_grid_coordenadas(lat: float, long: float, raio: float) -> list:
    """
    Retorna grid 3x3 ORDENADO para mosaico:
      - row 0 = NORTE (lat maior)
      - row 2 = SUL
      - col 0 = OESTE (lon menor / mais negativo)
      - col 2 = LESTE

    Cada item:
      {"row": int, "col": int, "lat": float, "lon": float, "tile_i": int}
    tile_i vai de 1..9 em row-major: (0,0)=1 ... (2,2)=9
    """
    meters_per_degree = 111139.0
    delta_lat = raio / meters_per_degree

    cos_lat = math.cos(math.radians(lat))
    if abs(cos_lat) < 1e-12:
        cos_lat = 1e-12
    delta_lon = raio / (meters_per_degree * cos_lat)

    step_lat = delta_lat * 0.5
    step_lon = delta_lon * 0.5

    grade = []
    tile_i = 1

    for row, i in enumerate([1, 0, -1]):        # norte -> sul
        for col, j in enumerate([-1, 0, 1]):    # oeste -> leste
            lat_nova = lat + (i * step_lat)
            long_nova = long + (j * step_lon)
            grade.append({
                "row": int(row),
                "col": int(col),
                "lat": float(lat_nova),
                "lon": float(long_nova),
                "tile_i": int(tile_i),
            })
            tile_i += 1

    return grade


def anexar_latlon_da_bbox(det, tile_lat, tile_lon, zoom, img_w, img_h):
    """
    Mantido como 'best effort'. Se você já tem uma versão melhor no seu projeto, use a sua.
    Aqui só retorna False (não quebra) se não der.
    """
    try:
        # placeholder: se você tiver sua implementação real, substitua esta função.
        return False
    except Exception:
        return False
