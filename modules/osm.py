import requests
from shapely.geometry import Polygon

OVERPASS_URL = "https://overpass-api.de/api/interpreter"


def query_overpass(lat: float, lon: float, radius: float, landuses: list[str]):
    """
    Consulta a Overpass API e retorna JSON bruto
    """
    landuse_str = "|".join(landuses)

    query = f"""
    [out:json][timeout:60];
    (
      way["landuse"~"{landuse_str}"](around:{radius},{lat},{lon});
      relation["landuse"~"{landuse_str}"](around:{radius},{lat},{lon});
    );
    out geom;
    """

    response = requests.post(OVERPASS_URL, data=query, timeout=60)
    response.raise_for_status()
    return response.json()


def parse_osm_polygons(overpass_json: dict):
    """
    Converte resposta Overpass em polígonos shapely normalizados
    """
    polygons = []

    for element in overpass_json.get("elements", []):
        tags = element.get("tags", {})
        landuse = tags.get("landuse")

        if not landuse or "geometry" not in element:
            continue

        coords = [(p["lon"], p["lat"]) for p in element["geometry"]]

        if len(coords) < 3:
            continue  # não é polígono válido

        polygons.append({
            "osm_id": f"{element['type']}/{element['id']}",
            "landuse": landuse,
            "geometry": Polygon(coords)
        })

    return polygons
