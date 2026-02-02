from shapely.geometry import Point

def spatial_join(detections: list[dict], polygons: list[dict]) -> list[dict]:

    result = []

    for det in detections:
        point = Point(det["lon"], det["lat"])
        landuse = next(
            (p["landuse"] for p in polygons if p["geometry"].contains(point)),
            "unknown"
        )

        result.append({
            **det,
            "landuse": landuse
        })

    return result


def aggregate_landuse(joined: list[dict]) -> dict:
    """
    Agrega contagem de painéis por uso do solo
    """
    summary = {}
    for item in joined:
        summary[item["landuse"]] = summary.get(item["landuse"], 0) + 1
    return summary
