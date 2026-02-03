from shapely.geometry import Point

try:
    from shapely.prepared import prep
except Exception:
    prep = None

_PRIORITY = {"industrial": 3, "commercial": 2, "residential": 1, "unknown": 0}

def spatial_join(detections: list[dict], polygons: list[dict]) -> list[dict]:
    # prepara geometrias (bem mais rápido)
    if prep is not None:
        prepared = [(prep(p["geometry"]), str(p.get("landuse", "unknown"))) for p in (polygons or [])]
        use_prepared = True
    else:
        prepared = [(p["geometry"], str(p.get("landuse", "unknown"))) for p in (polygons or [])]
        use_prepared = False

    result = []

    for det in detections or []:
        pt = Point(det["lon"], det["lat"])

        best = "unknown"
        best_score = 0

        for geom, lu in prepared:
            hit = (geom.contains(pt) or geom.intersects(pt)) if use_prepared else geom.covers(pt)
            if not hit:
                continue

            score = _PRIORITY.get(lu, 0)
            if score > best_score:
                best, best_score = lu, score
                if best_score == 3:  # industrial é o topo, pode parar cedo
                    break

        result.append({**det, "landuse": best})

    return result


def aggregate_landuse(joined: list[dict]) -> dict:
    summary = {}
    for item in joined or []:
        k = str(item.get("landuse", "unknown"))
        summary[k] = summary.get(k, 0) + 1
    return summary
