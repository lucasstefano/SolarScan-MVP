# modules/spatial_join.py
from __future__ import annotations

import math
from shapely.geometry import Point

try:
    from shapely.prepared import prep
except Exception:
    prep = None


_PRIORITY = {"industrial": 3, "commercial": 2, "residential": 1, "unknown": 0}


def _deg_to_meters_lat(d: float) -> float:
    return float(d) * 111_320.0


def _distance_deg_to_m(d_deg: float, lat: float) -> float:
    # aproximação em metros (bom o bastante pra 30–60m)
    return _deg_to_meters_lat(d_deg)


def spatial_join(
    detections: list[dict],
    polygons: list[dict],
    max_near_m: float = 60.0,
) -> list[dict]:
    """
    Faz join ponto->polígono.

    - Primário: contém/intersecta => confidence=HIGH
    - Fallback: polígono mais próximo até max_near_m => confidence=LOW
    """
    if prep is not None:
        prepared = [(prep(p["geometry"]), p["geometry"], str(p.get("landuse", "unknown"))) for p in (polygons or [])]
        use_prepared = True
    else:
        prepared = [(p["geometry"], p["geometry"], str(p.get("landuse", "unknown"))) for p in (polygons or [])]
        use_prepared = False

    result = []

    for det in detections or []:
        pt = Point(det["lon"], det["lat"])

        best = "unknown"
        best_score = 0
        conf = "HIGH"

        hit_any = False
        for geom_pre, geom_raw, lu in prepared:
            hit = (geom_pre.contains(pt) or geom_pre.intersects(pt)) if use_prepared else geom_raw.covers(pt)
            if not hit:
                continue
            hit_any = True

            score = _PRIORITY.get(lu, 0)
            if score > best_score:
                best, best_score = lu, score
                if best_score == 3:
                    break

        if not hit_any and prepared:
            nearest_lu = "unknown"
            nearest_score = 0
            nearest_m = None

            for _, geom_raw, lu in prepared:
                try:
                    d_deg = geom_raw.distance(pt)
                    d_m = _distance_deg_to_m(d_deg, det["lat"])
                except Exception:
                    continue

                if d_m <= float(max_near_m):
                    score = _PRIORITY.get(lu, 0)
                    if (score > nearest_score) or (score == nearest_score and (nearest_m is None or d_m < nearest_m)):
                        nearest_score = score
                        nearest_lu = lu
                        nearest_m = d_m

            if nearest_m is not None and nearest_score > 0:
                det2 = {**det, "landuse": nearest_lu, "landuse_confidence": "LOW", "landuse_near_m": round(float(nearest_m), 1)}
                result.append(det2)
                continue

        result.append({**det, "landuse": best, "landuse_confidence": conf})

    return result


def aggregate_landuse(joined: list[dict]) -> dict:
    summary = {}
    for item in joined or []:
        k = str(item.get("landuse", "unknown"))
        summary[k] = summary.get(k, 0) + 1
    return summary
