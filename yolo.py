import os
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from ultralytics import YOLO


@lru_cache(maxsize=1)
def _load_model():
    """
    Carrega o modelo com sistema de fallback (segurança).
    Tenta carregar o modelo customizado; se falhar, carrega o oficial.
    """
    project_root = Path(__file__).resolve().parent
    default_weights = project_root / "models" / "best.pt"

    weights_path = Path(os.getenv("YOLO_WEIGHTS", str(default_weights)))
    if not weights_path.is_absolute():
        weights_path = (project_root / weights_path).resolve()

    print(f"[YOLO] Tentando carregar modelo: {weights_path}", flush=True)

    try:
        if weights_path.exists():
            return YOLO(str(weights_path))
        print(f"[YOLO] Aviso: Arquivo {weights_path} não existe.", flush=True)
        raise FileNotFoundError("Modelo customizado não encontrado")

    except Exception as e:
        print(f"[YOLO] ⚠️ ERRO CRÍTICO ao carregar '{weights_path.name}': {e}", flush=True)
        print("[YOLO] 🔄 Ativando FALLBACK: Usando modelo padrão 'yolov8n.pt'...", flush=True)
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

        results = model.predict(img, conf=conf, verbose=False)

        deteccoes = []
        for r in results:
            if r.boxes is None:
                continue
            for b in r.boxes:
                x1, y1, x2, y2 = b.xyxy[0].tolist()
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
        print(f"[YOLO] Erro na inferência: {e}", flush=True)
        return []


def salvar_imagem_com_boxes(
    imagem_bytes: bytes,
    deteccoes: list,
    out_path: str | Path,
    min_conf: float | None = None,
    draw_labels: bool = True,
) -> Path | None:
    """
    Desenha as boxes (vindas do detectar_paineis_imagem) e salva em out_path.
    Não roda inferência de novo.
    """
    if not imagem_bytes:
        return None

    try:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        img = Image.open(BytesIO(imagem_bytes)).convert("RGB")
        draw = ImageDraw.Draw(img)

        try:
            font = ImageFont.load_default()
        except Exception:
            font = None

        total = 0
        for d in (deteccoes or []):
            confv = float(d.get("confidence", 0.0))
            if min_conf is not None and confv < float(min_conf):
                continue

            x1 = float(d["x"])
            y1 = float(d["y"])
            x2 = x1 + float(d["width"])
            y2 = y1 + float(d["height"])

            draw.rectangle([x1, y1, x2, y2], outline="lime", width=3)
            total += 1

            if draw_labels:
                cls = int(d.get("class_id", -1))
                label = f"cls={cls} {confv:.2f}"
                if font is not None:
                    bbox = draw.textbbox((0, 0), label, font=font)
                    text_w = bbox[2] - bbox[0]
                    text_h = bbox[3] - bbox[1]
                else:
                    text_w, text_h = (60, 12)

                pad = 4
                tx1, ty1 = x1, max(0, y1 - (text_h + pad * 2))
                tx2, ty2 = x1 + text_w + pad * 2, ty1 + text_h + pad * 2
                draw.rectangle([tx1, ty1, tx2, ty2], fill="black")
                draw.text((tx1 + pad, ty1 + pad), label, fill="white", font=font)

        img.save(out_path)
        print(f"[YOLO] ✅ imagem com boxes salva: {out_path} | boxes={total}", flush=True)
        return out_path

    except Exception as e:
        print(f"[YOLO] Erro ao salvar imagem com boxes: {e}", flush=True)
        return None
