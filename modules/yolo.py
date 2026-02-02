import os
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from PIL import Image
from ultralytics import YOLO

@lru_cache(maxsize=1)
def _load_model():
    """
    Carrega o modelo com sistema de fallback (segurança).
    Tenta carregar o modelo customizado; se falhar, carrega o oficial.
    """
    # ✅ raiz correta (mesma pasta do yolo.py)
    project_root = Path(__file__).resolve().parent
    default_weights = project_root / "models" / "best.pt"

    weights_path = Path(os.getenv("YOLO_WEIGHTS", str(default_weights)))

    if not weights_path.is_absolute():
        weights_path = (project_root / weights_path).resolve()

    print(f"[YOLO] Tentando carregar modelo: {weights_path}", flush=True)

    try:
        if weights_path.exists():
            return YOLO(str(weights_path))
        else:
            print(f"[YOLO] Aviso: Arquivo {weights_path} não existe.", flush=True)
            raise FileNotFoundError("Modelo customizado não encontrado")

    except Exception as e:
        print(f"[YOLO] ⚠️ ERRO CRÍTICO ao carregar '{weights_path.name}': {e}", flush=True)
        print("[YOLO] 🔄 Ativando FALLBACK: Baixando/Usando modelo padrão 'yolov8n.pt'...", flush=True)
        return YOLO("yolov8n.pt")

def detectar_paineis_imagem(imagem_bytes: bytes) -> list:
    """
    Executa inferência YOLOv8 e retorna lista de detecções.
    """
    if not imagem_bytes:
        return []

    try:
        model = _load_model()
        img = Image.open(BytesIO(imagem_bytes)).convert("RGB")
        conf = float(os.getenv("YOLO_CONF", "0.25"))

        # Executa predição
        results = model.predict(
            source=img,
            conf=0.45,
            iou=0.5,
            imgsz=960,
            max_det=120,
            verbose=False,
        )


        deteccoes = []
        for r in results:
            if r.boxes is None:
                continue
            for b in r.boxes:
                xyxy = b.xyxy[0].tolist()
                x1, y1, x2, y2 = xyxy
                confv = float(b.conf[0]) if b.conf is not None else 0.0
                cls = int(b.cls[0]) if b.cls is not None else -1

                deteccoes.append({
                    "x": float(x1),
                    "y": float(y1),
                    "width": float(x2 - x1),
                    "height": float(y2 - y1),
                    "confidence": confv,
                    "class_id": cls,
                })
        return deteccoes

    except Exception as e:
        print(f"[YOLO] Erro na inferência: {e}")
        return []