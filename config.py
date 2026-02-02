# Configurações de API
GOOGLE_MAPS_API_KEY = "SUA_CHAVE_AQUI"  
URL_OSM_OVERPASS = "https://overpass-api.de/api/interpreter"

# Configurações de processamento de Imagem
TAMANHO_GRADE_PADRAO = 640
CAMINHO_MODELO_YOLO = "models/yolov8s_solar.pt"
LIMIAR_CONFIANCA_YOLO = 0.5

RAIO_MINIMO_METROS = 500.0 # Raio Mínimo: Garante área útil mínima mesmo em centros densos
RAIO_MAXIMO_METROS = 5000.0 # Raio Máximo (Teto): Evita estourar custos de API em áreas rurais isoladas
RAIO_PADRAO_METROS = 1500.0 # Raio Padrão (Fallback): Usado quando não há vizinhos para comparar (n=1)
RAIO_TERRA_METROS = 6371000.0 # Constantes Físicas

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
    "risco_curva_pato"
]