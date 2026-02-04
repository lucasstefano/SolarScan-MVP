import os
import time
import random
import requests

try:
    import certifi
except Exception:
    certifi = None

"""
Módulo para aquisição de imagens de satélite.

⚠️ Importante:
- NÃO hardcode API keys no código.
- Use GOOGLE_MAPS_API_KEY via variável de ambiente.
"""

GOOGLE_STATIC_MAPS_URL = "https://maps.googleapis.com/maps/api/staticmap"


def baixar_imagem_tile(
    lat: float,
    lon: float,
    zoom: int = 20,
    size: str = "640x640",
    scale: int = 2,
    img_format: str = "png",
    timeout_s: int = 20,
    retries: int = 3,
) -> bytes:
    """
    Baixa imagem de satélite do Google Maps Static API.

    Args:
        lat/lon: centro do tile
        zoom: zoom (deve ser consistente com geo_calculos.anexar_latlon_da_bbox)
        size: ex "640x640"
        scale: 1 ou 2
        img_format: "png" ou "jpg"
        timeout_s: timeout do request
        retries: tentativas com backoff para 429/5xx
    """
    api_key = "AIzaSyAHbiO3fZ-GUeg6g-Q53qyJnZ9Q0F_54Sc"
    if not api_key:
        raise RuntimeError("Defina a variável de ambiente GOOGLE_MAPS_API_KEY")

    params = {
        "center": f"{lat},{lon}",
        "zoom": str(int(zoom)),
        "size": size,
        "scale": str(int(scale)),
        "maptype": "satellite",
        "format": img_format,
        "key": api_key,
    }

    headers = {"User-Agent": "SolarScan/1.0 (+tile-downloader)"}

    # Em alguns ambientes Windows, isso resolve travas/erros de SSL no requests
    verify = certifi.where() if certifi is not None else True

    last_err = None
    for attempt in range(retries + 1):
        try:
            r = requests.get(
                GOOGLE_STATIC_MAPS_URL,
                params=params,
                headers=headers,
                timeout=timeout_s,
                verify=verify,
            )

            if r.status_code in (429, 500, 502, 503, 504):
                last_err = RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
                if attempt < retries:
                    sleep_s = (0.8 * (2 ** attempt)) + random.random() * 0.25
                    time.sleep(sleep_s)
                    continue
                raise last_err

            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")

            content_type = (r.headers.get("Content-Type") or "").lower()
            if "image" not in content_type:
                raise RuntimeError(
                    f"Resposta não é imagem. Content-Type={content_type}. Body={r.text[:300]}"
                )

            return r.content

        except Exception as e:
            last_err = e
            if attempt < retries:
                sleep_s = (0.8 * (2 ** attempt)) + random.random() * 0.25
                time.sleep(sleep_s)
                continue
            raise RuntimeError(
                f"Falha ao baixar tile ({lat},{lon}) zoom={zoom}: {e}"
            ) from e
