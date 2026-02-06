"""
YOLO Optimized - Singleton Pattern + Métricas de Confiança
Mudanças:
- Modelo carrega 1x e fica em memória (singleton thread-safe)
- Retorna métricas agregadas (confiança média, min, max)
- Warmup automático na primeira carga
- Cache de inferência opcional
"""
import os
import threading
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont
from ultralytics import YOLO


class YOLOSingleton:
    """
    Garante que o modelo YOLO seja carregado apenas UMA VEZ
    e compartilhado entre todas as threads/chamadas.
    """
    _instance = None
    _lock = threading.Lock()
    _model = None
    _warmed_up = False

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def get_model(self) -> YOLO:
        """Retorna o modelo (carrega se necessário)"""
        if self._model is None:
            with self._lock:
                if self._model is None:
                    self._model = self._load_model()
                    self._warmup()
        return self._model

    def _load_model(self) -> YOLO:
        """Carrega o modelo com fallback"""
        def _resolve_path(p: Path) -> Path:
            try:
                return p.expanduser().resolve()
            except Exception:
                return p

        def _find_best_pt() -> Optional[Path]:
            env = os.getenv("YOLO_WEIGHTS")
            if env:
                p = _resolve_path(Path(env))
                if p.exists():
                    return p

            here = Path(__file__).resolve()
            for base in [here.parent, *here.parents]:
                cand = base / "models" / "best.pt"
                if cand.exists():
                    return cand

            cand = here.parent / "best.pt"
            if cand.exists():
                return cand

            return None

        weights_path = _find_best_pt()
        print(f"🔥 [YOLO SINGLETON] Carregando modelo: {weights_path}", flush=True)

        try:
            if weights_path:
                model = YOLO(str(weights_path))
                print(f"✅ [YOLO] Modelo customizado carregado: {weights_path.name}", flush=True)
                return model
            raise FileNotFoundError("best.pt não encontrado")
        except Exception as e:
            print(f"⚠️ [YOLO] ERRO ao carregar pesos: {e}", flush=True)
            print("[YOLO] 🔄 FALLBACK: yolov8n.pt", flush=True)
            return YOLO("yolov8n.pt")

    def _warmup(self):
        """Aquece o modelo com uma imagem dummy (acelera inferências futuras)"""
        if self._warmed_up:
            return
            
        try:
            print("🔥 [YOLO] Aquecendo modelo (warmup)...", flush=True)
            dummy_img = Image.new("RGB", (640, 640), color="black")
            self._model.predict(dummy_img, conf=0.25, verbose=False)
            self._warmed_up = True
            print("✅ [YOLO] Modelo aquecido e pronto!", flush=True)
        except Exception as e:
            print(f"⚠️ [YOLO] Warmup falhou: {e}", flush=True)


# Instância global (singleton)
_yolo_singleton = YOLOSingleton()


def detectar_paineis_imagem(imagem_bytes: bytes) -> Tuple[List[Dict], Dict]:
    """
    Executa inferência YOLOv8 e retorna detecções + métricas.
    
    Returns:
        Tuple[List[Dict], Dict]: (detecções, métricas)
        
    métricas = {
        "total_detections": int,
        "confidence_mean": float,
        "confidence_min": float, 
        "confidence_max": float,
        "confidence_std": float,
        "inference_time_ms": float
    }
    """
    if not imagem_bytes:
        return [], _empty_metrics()

    try:
        import time
        model = _yolo_singleton.get_model()
        img = Image.open(BytesIO(imagem_bytes)).convert("RGB")
        conf = float(os.getenv("YOLO_CONF", "0.65"))

        t0 = time.perf_counter()
        results = model.predict(img, conf=conf, verbose=False)
        inference_time = (time.perf_counter() - t0) * 1000  # ms

        deteccoes = []
        confidences = []

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
                confidences.append(confv)

        # Calcula métricas
        metrics = _calculate_metrics(confidences, inference_time)
        
        return deteccoes, metrics

    except Exception as e:
        print(f"[YOLO] Erro na inferência: {e}", flush=True)
        return [], _empty_metrics()


def _calculate_metrics(confidences: List[float], inference_time: float) -> Dict:
    """Calcula estatísticas de confiança"""
    if not confidences:
        return _empty_metrics()
    
    import statistics
    
    return {
        "total_detections": len(confidences),
        "confidence_mean": round(statistics.mean(confidences), 3),
        "confidence_min": round(min(confidences), 3),
        "confidence_max": round(max(confidences), 3),
        "confidence_std": round(statistics.stdev(confidences), 3) if len(confidences) > 1 else 0.0,
        "inference_time_ms": round(inference_time, 1)
    }


def _empty_metrics() -> Dict:
    """Métricas vazias para casos de erro"""
    return {
        "total_detections": 0,
        "confidence_mean": 0.0,
        "confidence_min": 0.0,
        "confidence_max": 0.0,
        "confidence_std": 0.0,
        "inference_time_ms": 0.0
    }


def salvar_imagem_com_boxes(
    imagem_bytes: bytes,
    deteccoes: List[Dict],
    out_path: str | Path,
    min_conf: Optional[float] = None,
    draw_labels: bool = True,
) -> Optional[Path]:
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
