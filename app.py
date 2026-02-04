from __future__ import annotations

from flask import Flask, render_template_string, request, jsonify, send_file, Response
import json
import time
import queue
import threading
import secrets
import os
from pathlib import Path

app = Flask(__name__)

HTML = r"""
<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>SolarScan - Mosaic RAW + Overlay</title>

  <style>
    body { font-family: Arial, sans-serif; background:#0f2a4d; margin:0; padding:20px; }
    .wrap { background:#fff; border-radius:14px; overflow:hidden; max-width:1200px; margin:0 auto; box-shadow:0 15px 40px rgba(0,0,0,.35);}
    .top { background:#f39c12; color:#fff; padding:16px 20px; font-weight:700; }
    .row { display:flex; gap:20px; padding:20px; }

    .left { width:320px; }
    .left label { display:block; font-size:12px; margin:10px 0 6px; font-weight:700; color:#1e3c72;}
    .left input, .left textarea { width:100%; padding:10px; border:2px solid #e6e6e6; border-radius:8px; font-size:13px;}
    .left textarea { height:110px; font-family: monospace; }
    .btn { width:100%; padding:12px; border:0; border-radius:10px; background:#f39c12; color:#fff; font-weight:800; cursor:pointer; margin-top:12px; }
    .btn:disabled { background:#e9ecef; color:#999; cursor:not-allowed; }

    .right { flex:1; }
    .bar { height:8px; background:#eee; border-radius:10px; overflow:hidden; margin-bottom:12px; }
    .bar > div { height:100%; width:0%; background:#f39c12; transition:width .15s; }

    /* MOSAICO sem borda/gap */
    .mosaic-wrap { position:relative; width:100%; max-width:820px; aspect-ratio:1; background:#000; overflow:hidden; border-radius:12px; }
    .mosaic {
      position:absolute; inset:0;
      display:grid;
      grid-template-columns:repeat(3, 1fr);
      grid-template-rows:repeat(3, 1fr);
      gap:0;
      padding:0;
      margin:0;
    }
    .tile { position:relative; overflow:hidden; background:#111; }
    .tile img { width:100%; height:100%; object-fit:cover; display:block; user-select:none; -webkit-user-drag:none; }

    /* Overlay boxes por cima do mosaico inteiro */
    .overlay { position:absolute; inset:0; pointer-events:none; }
    .det { position:absolute; border:2px solid #00ff66; box-sizing:border-box; pointer-events:auto; }
    .det:hover { border-color:#ffd000; }

    .tip {
      position:absolute;
      left:0; top:-26px;
      background:rgba(0,0,0,.85);
      color:#fff;
      font-size:11px;
      padding:4px 6px;
      border-radius:6px;
      white-space:nowrap;
      display:none;
      transform:translateY(-4px);
    }
    .det:hover .tip { display:block; }

    .stats { margin-top:12px; font-size:13px; color:#333; }
    .pill { display:inline-block; padding:6px 10px; border-radius:999px; background:#f2f4f7; margin-right:8px; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="top">SolarScan — Mosaic RAW + Overlay (center-out + dedup)</div>

    <div class="row">
      <div class="left">
        <label>JSON (subestações)</label>
        <textarea id="json">[{"id":"SUB_BTF_CENTRO","lat":-22.994598,"lon":-43.377366}]</textarea>

        <label>Raio (m)</label>
        <input id="raio" type="number" value="2000" />

        <button class="btn" id="go" onclick="start()">Iniciar</button>

        <div class="stats" id="stats"></div>
      </div>

      <div class="right">
        <div class="bar"><div id="pbar"></div></div>

        <div class="mosaic-wrap">
          <div class="mosaic" id="mosaic"></div>
          <div class="overlay" id="overlay"></div>
        </div>
      </div>
    </div>
  </div>

<script>
  let es = null;

  function keyRC(r,c){ return `r${r}c${c}`; }

  function setupMosaic() {
    const m = document.getElementById("mosaic");
    m.innerHTML = "";
    for (let r=0;r<3;r++){
      for (let c=0;c<3;c++){
        const d = document.createElement("div");
        d.className = "tile";
        d.id = `tile_${keyRC(r,c)}`;
        d.innerHTML = `<img alt="" src="" style="opacity:.15" />`;
        m.appendChild(d);
      }
    }
    document.getElementById("overlay").innerHTML = "";
    document.getElementById("pbar").style.width = "0%";
    document.getElementById("stats").innerHTML = "";
  }

  function setTileImage(row, col, url) {
    const tile = document.getElementById(`tile_${keyRC(row,col)}`);
    if (!tile) return;
    const img = tile.querySelector("img");
    img.src = url + `?t=${Date.now()}`;
    img.style.opacity = "1";
  }

  // mantém boxes por id pra substituição/remoção
  const detDomById = new Map();

  function removeDetById(id) {
    const el = detDomById.get(id);
    if (el) {
      el.remove();
      detDomById.delete(id);
    }
  }

  function addDetBox(det) {
    // det: {id, bbox_pct:{left,top,width,height}, confidence, ...}
    const ov = document.getElementById("overlay");
    const box = document.createElement("div");
    box.className = "det";
    box.dataset.detId = det.id;

    box.style.left = det.bbox_pct.left + "%";
    box.style.top = det.bbox_pct.top + "%";
    box.style.width = det.bbox_pct.width + "%";
    box.style.height = det.bbox_pct.height + "%";

    const conf = (det.confidence ?? 0).toFixed(2);
    const lat = det.lat != null ? Number(det.lat).toFixed(6) : null;
    const lon = det.lon != null ? Number(det.lon).toFixed(6) : null;

    const extra = (lat && lon) ? ` | ${lat},${lon}` : "";
    box.innerHTML = `<div class="tip">painel | conf ${conf}${extra}</div>`;

    ov.appendChild(box);
    detDomById.set(det.id, box);
  }

  async function start() {
    setupMosaic();
    document.getElementById("go").disabled = true;

    let subs = [];
    try { subs = JSON.parse(document.getElementById("json").value.trim()); }
    catch(e){ alert("JSON inválido"); document.getElementById("go").disabled = false; return; }
    if (!subs.length) { alert("Subestações vazias"); document.getElementById("go").disabled = false; return; }

    const sub = subs[0];
    const raio = Number(document.getElementById("raio").value || 2000);

    if (es) { es.close(); es=null; detDomById.clear(); }

    const qs = new URLSearchParams({
      id: sub.id,
      lat: String(sub.lat),
      lon: String(sub.lon),
      raio: String(raio),
    });

    es = new EventSource(`/api/analisar-stream?${qs.toString()}`);

    es.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);

      if (msg.type === "sub_start") {
        document.getElementById("stats").innerHTML =
          `<span class="pill">run: ${msg.run_id}</span><span class="pill">sub: ${msg.sub_id}</span>
           <span class="pill">prioridade: center-out</span>`;
      }

      if (msg.type === "tile_ready") {
        const url = `/api/run-file/${msg.run_id}/${msg.sub_id}/raw/${msg.raw_name}`;
        setTileImage(msg.row, msg.col, url);
      }

      // backend já faz dedup e manda eventos incrementais:
      // - replaced_id: remover box antigo
      // - new_det: adicionar box novo (com bbox_pct)
      if (msg.type === "det_add") {
        if (msg.replaced_id) removeDetById(msg.replaced_id);

        // o backend pode mandar new_det com id já preenchido;
        // se vier null por algum motivo, ignora
        const d = msg.new_det;
        if (d && d.id && d.bbox_pct) addDetBox(d);
      }

      if (msg.type === "progress") {
        document.getElementById("pbar").style.width = (msg.pct || 0) + "%";
        document.getElementById("stats").innerHTML =
          `<span class="pill">run: ${msg.run_id}</span>
           <span class="pill">tiles: ${msg.done}/${msg.total}</span>
           <span class="pill">boxes: ${msg.det_emitted}</span>`;
      }

      if (msg.type === "tile_fail") {
        console.warn("tile_fail", msg);
      }

      if (msg.type === "done") {
        es.close(); es=null;
        document.getElementById("pbar").style.width = "100%";
        document.getElementById("go").disabled = false;
      }

      if (msg.type === "error") {
        alert("Erro: " + (msg.error || "desconhecido"));
        es.close(); es=null;
        document.getElementById("go").disabled = false;
      }
    };

    es.onerror = () => {
      console.warn("SSE error");
      if (es) es.close();
      es=null;
      document.getElementById("go").disabled = false;
    };
  }
</script>
</body>
</html>
"""

def _safe_join(base: Path, *parts: str) -> Path:
    p = (base / Path(*parts)).resolve()
    if str(p).startswith(str(base.resolve())):
        return p
    raise ValueError("path traversal bloqueado")


@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/api/run-file/<run_id>/<sub_id>/raw/<filename>")
def run_file(run_id: str, sub_id: str, filename: str):
    debug_root = Path(os.getenv("DEBUG_DIR", "debug_runs")).resolve()
    fp = _safe_join(debug_root, run_id, sub_id, "raw", filename)
    if not fp.exists():
        return jsonify({"error": "arquivo não encontrado"}), 404
    return send_file(str(fp), mimetype="image/png")


@app.route("/api/analisar-stream")
def analisar_stream():
    sub_id = (request.args.get("id") or "SUB").strip()
    lat = float(request.args.get("lat") or "0")
    lon = float(request.args.get("lon") or "0")
    raio = float(request.args.get("raio") or "2000")

    run_id = f"{int(time.time())}_{secrets.token_hex(4)}"
    q: "queue.Queue[dict]" = queue.Queue()

    def emit(msg: dict):
        msg = dict(msg or {})
        msg.setdefault("run_id", run_id)
        msg.setdefault("sub_id", sub_id)
        q.put(msg)

    def worker():
        try:
            from pipeline import pipeline_stream_mosaico
            pipeline_stream_mosaico({"id": sub_id, "lat": lat, "lon": lon}, raio, run_id=run_id, emit=emit)
        except Exception as e:
            emit({"type": "error", "error": str(e)})

    threading.Thread(target=worker, daemon=True).start()

    def stream():
        yield "retry: 1500\n\n"
        while True:
            try:
                msg = q.get(timeout=30)
            except queue.Empty:
                yield ": keep-alive\n\n"
                continue
            yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
            if msg.get("type") in ("done", "error"):
                break

    return Response(stream(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True, threaded=True)
