from shapely.geometry import Point


def spatial_join_panels_with_landuse(detections: list[dict], polygons: list[dict]):
    """
    Associa cada painel detectado a um tipo de uso do solo
    """
    results = []

    for det in detections:
        point = Point(det["lon"], det["lat"])
        matched_landuse = "unknown"

        for poly in polygons:
            if poly["geometry"].contains(point):
                matched_landuse = poly["landuse"]
                break

        results.append({
            "lat": det["lat"],
            "lon": det["lon"],
            "confidence": det["confidence"],
            "landuse": matched_landuse
        })

    return results


def aggregate_by_landuse(joined_data: list[dict]):
    """
    Agrega quantidade de painéis por tipo de uso do solo
    """
    summary = {}

    for item in joined_data:
        lu = item["landuse"]
        summary[lu] = summary.get(lu, 0) + 1

    return summary
