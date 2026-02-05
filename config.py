import os
from dotenv import load_dotenv

# Carrega as variáveis do arquivo .env para o os.environ
load_dotenv()

# --- Configurações de API ---
# Agora pega do .env. Se não achar, retorna string vazia ou erro.
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

if not GOOGLE_MAPS_API_KEY:
    print("⚠️  AVISO: GOOGLE_MAPS_API_KEY não encontrada no arquivo .env!")

URL_OSM_OVERPASS = "https://overpass-api.de/api/interpreter"

# --- Configurações de processamento de Imagem ---
TAMANHO_GRADE_PADRAO = 640  # Mantido para referência legado
CAMINHO_MODELO_YOLO = os.getenv("YOLO_WEIGHTS", "models/yolov8s_solar.pt")
LIMIAR_CONFIANCA_YOLO = float(os.getenv("YOLO_CONF", "0.5"))

# --- Constantes Físicas e Limites (Podem vir do ENV ou ficar hardcoded) ---
RAIO_MINIMO_METROS = float(os.getenv("RAIO_MINIMO_METROS", "500.0"))
RAIO_MAXIMO_METROS = float(os.getenv("RAIO_MAXIMO_METROS", "5000.0"))
RAIO_PADRAO_METROS = float(os.getenv("RAIO_PADRAO_METROS", "1500.0"))
RAIO_TERRA_METROS = 6371000.0

# --- Configurações de saída ---
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