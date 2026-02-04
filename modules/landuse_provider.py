# modules/landuse_provider.py
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

from modules.rio_provider import is_inside_rio_bbox, query_rio_polygons
from modules.osm import obter_poligonos_osm


BASE_DIR = Path(__file__).resolve().parent.parent 

# Constrói o caminho a partir da raiz do projeto
DEFAULT_RIO_GEOJSON_PATH = os.getenv(
    "RIO_USO_GEOJSON",
    str(BASE_DIR / "data" / "rio" / "USO_DO_SOLO_2019.geojson")
)

def get_landuse_polygons(
    lat: float,
    lon: float,
    radius_m: float,
    region_hint: Optional[str] = None,
    rio_geojson_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Cadeia de providers:
      - DATA.RIO (primário no RJ, se arquivo existir)
      - fallback OSM melhorado
      - nacional: OSM melhorado
    """
    rio_path = rio_geojson_path or DEFAULT_RIO_GEOJSON_PATH
    rio_exists = Path(rio_path).exists()

    use_rio = False
    if region_hint and str(region_hint).strip().upper() == "RJ":
        use_rio = True
    elif is_inside_rio_bbox(lat, lon):
        use_rio = True
    print("a", use_rio)
    if use_rio and rio_exists:
        try:
            polys = query_rio_polygons(rio_path, lat, lon, radius_m) or []
            print("RIO polys:", len(polys))

            if polys:
                return {"polygons": polys, "success": True, "provider": "DATA.RIO", "source_path": rio_path}

            osm = obter_poligonos_osm(lat, lon, radius_m)
            osm["provider"] = "OSM"
            osm["fallback_reason"] = "DATA.RIO vazio (sem match)"
            return osm

        except Exception as e:
            osm = obter_poligonos_osm(lat, lon, radius_m)
            osm["provider"] = "OSM"
            osm["fallback_reason"] = f"DATA.RIO falhou: {e}"
            return osm

    osm = obter_poligonos_osm(lat, lon, radius_m)
    osm["provider"] = "OSM"
    if use_rio and not rio_exists:
        osm["fallback_reason"] = f"DATA.RIO ausente em {rio_path}"
    return osm
