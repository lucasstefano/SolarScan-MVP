# config_optimized.py
"""
Configurações otimizadas com validações e defaults inteligentes
"""
import os
from dotenv import load_dotenv

# Carrega as variáveis do arquivo .env
load_dotenv()

# --- APIs ---
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

if not GOOGLE_MAPS_API_KEY:
    print("⚠️  AVISO: GOOGLE_MAPS_API_KEY não encontrada no arquivo .env!")

URL_OSM_OVERPASS = "https://overpass-api.de/api/interpreter"

# --- YOLO ---
CAMINHO_MODELO_YOLO = os.getenv("YOLO_WEIGHTS", "models/best.pt")
LIMIAR_CONFIANCA_YOLO = float(os.getenv("YOLO_CONF", "0.25"))  # Lowered para mais detecções

# 🔥 NOVAS CONFIGS DE PERFORMANCE
IMAGE_CACHE_ENABLED = os.getenv("IMAGE_CACHE", "true").lower() == "true"
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "6"))  # Threads paralelas
TILE_ZOOM = int(os.getenv("TILE_ZOOM", "20"))
TILE_SIZE = os.getenv("TILE_SIZE", "640x640")
TILE_SCALE = int(os.getenv("TILE_SCALE", "2"))

# --- Limites Físicos ---
RAIO_MINIMO_METROS = float(os.getenv("RAIO_MINIMO_METROS", "500.0"))
RAIO_MAXIMO_METROS = float(os.getenv("RAIO_MAXIMO_METROS", "5000.0"))
RAIO_PADRAO_METROS = float(os.getenv("RAIO_PADRAO_METROS", "1500.0"))
RAIO_TERRA_METROS = 6371000.0

# --- Output Fields ---
OUTPUT_FIELDS = [
    "id_subestacao",
    "latitude_sub",
    "longitude_sub",
    "perfil_predominante",
    "%_residencial",
    "%_industrial",
    "%_comercial",
    "qnt_aprox_placa",
    "penetracao_mmgd",
    "risco_duck_curve",
    # 🔥 NOVOS CAMPOS
    "yolo_confidence_mean",
    "yolo_confidence_min",
    "yolo_confidence_max",
    "total_tiles_processed"
]

# --- Validações ---
def validate_config():
    """Valida configurações críticas"""
    issues = []
    
    if not GOOGLE_MAPS_API_KEY:
        issues.append("GOOGLE_MAPS_API_KEY missing")
    
    if LIMIAR_CONFIANCA_YOLO < 0.1 or LIMIAR_CONFIANCA_YOLO > 0.9:
        issues.append(f"YOLO_CONF={LIMIAR_CONFIANCA_YOLO} fora do range recomendado (0.1-0.9)")
    
    if MAX_WORKERS < 1 or MAX_WORKERS > 20:
        issues.append(f"MAX_WORKERS={MAX_WORKERS} fora do range (1-20)")
    
    if TILE_ZOOM < 18 or TILE_ZOOM > 21:
        issues.append(f"TILE_ZOOM={TILE_ZOOM} fora do range recomendado (18-21)")
    
    return issues

if __name__ == "__main__":
    issues = validate_config()
    if issues:
        print("⚠️  Problemas de configuração detectados:")
        for issue in issues:
            print(f"   - {issue}")
    else:
        print("✅ Todas as configurações estão válidas!")
