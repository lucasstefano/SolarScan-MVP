import os
import time
import random
import requests
from config import GOOGLE_MAPS_API_KEY  # <--- Importa a chave carregada do .env

try:
    import certifi
except ImportError:
    certifi = None

"""
Módulo para aquisição de imagens de satélite.
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
    """
    # Verifica se a chave foi carregada corretamente
    if not GOOGLE_MAPS_API_KEY:
        raise RuntimeError("Defina a variável GOOGLE_MAPS_API_KEY no arquivo .env")

    params = {
        "center": f"{lat},{lon}",
        "zoom": str(int(zoom)),
        "size": size,
        "scale": str(int(scale)),
        "maptype": "satellite",
        "format": img_format,
        "key": GOOGLE_MAPS_API_KEY,  # <--- Usa a variável importada
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
                # Se a chave estiver errada, o erro vai aparecer aqui (403 Forbidden)
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