"""
Configurações e constantes globais do SolarScan.
"""

# Configurações de API
GOOGLE_MAPS_API_KEY = "SUA_CHAVE_AQUI"  # TODO: Adicionar chave real
OSM_OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Configurações de processamento
DEFAULT_GRID_SIZE = 640  # pixels
YOLO_MODEL_PATH = "models/yolov8s_solar.pt"  # TODO: Baixar modelo treinado
YOLO_CONFIDENCE_THRESHOLD = 0.5

# Configurações de saída
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
    "risco_duck_curve"
]