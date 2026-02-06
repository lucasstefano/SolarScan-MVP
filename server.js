// server.js
import "dotenv/config"; // ✅ Garante que variáveis do .env (como PORT) sejam carregadas no Node
import express from "express";
import cors from "cors";
import { spawn } from "node:child_process";

const app = express();

// Aumente o limite se estiver enviando/recebendo base64 pesado
app.use(express.json({ limit: "50mb" }));

app.use(cors({ origin: true }));

const PORT = process.env.PORT || 3000;
const PYTHON_BIN = process.env.PYTHON_BIN || "python"; // Ou 'python3' em Linux/Mac
const RUNNER = process.env.PY_RUNNER || "runner.py";

// --- Helpers de Normalização ---

function normalizeOne(x) {
  if (!x || typeof x !== "object") return x;
  return {
    id: x.id ?? x.sub_id ?? x.subId ?? `temp_${Date.now()}`,
    lat: parseFloat(x.lat ?? x.latitude),
    lon: parseFloat(x.lon ?? x.lng ?? x.longitude),
    raio_m: parseFloat(x.raio_m ?? x.raio ?? x.radius_m ?? 300),
    ...x,
  };
}

function normalizePayload(payload) {
  if (Array.isArray(payload)) return payload.map(normalizeOne);
  return normalizeOne(payload);
}

/**
 * Tenta extrair o último JSON válido de uma string que pode conter logs/warnings.
 * Isso impede que warnings do pip ou logs soltos quebrem o parse.
 */
function extractJSON(raw) {
  try {
    // Tentativa direta
    return JSON.parse(raw);
  } catch (e) {
    // Tentativa robusta: encontrar o primeiro '{' e o último '}'
    const firstBrace = raw.indexOf("{");
    const lastBrace = raw.lastIndexOf("}");
    
    if (firstBrace !== -1 && lastBrace !== -1 && lastBrace > firstBrace) {
      try {
        const jsonStr = raw.substring(firstBrace, lastBrace + 1);
        return JSON.parse(jsonStr);
      } catch (innerE) {
        return null;
      }
    }
    return null;
  }
}

function runPython(payload) {
  return new Promise((resolve, reject) => {
    const p = spawn(PYTHON_BIN, [RUNNER], {
      env: process.env, // Passa as envs do Node para o Python
      stdio: ["pipe", "pipe", "pipe"],
    });

    let stdout = "";
    let stderr = "";
    
    // Timeout de segurança (2 minutos)
    const timeout = setTimeout(() => {
        p.kill();
        reject({ code: "TIMEOUT", error: "Python script timed out after 120s" });
    }, 120000);

    p.stdout.on("data", (d) => (stdout += d.toString("utf-8")));
    p.stderr.on("data", (d) => (stderr += d.toString("utf-8")));

    p.on("error", (err) => {
        clearTimeout(timeout);
        reject(err);
    });

    p.on("close", (code) => {
      clearTimeout(timeout);
      
      try {
        // 🔥 Limpeza: Remove linhas em branco extras
        const cleanOutput = stdout.trim();
        const parsed = extractJSON(cleanOutput);

        if (!parsed) {
             // Se não conseguiu extrair JSON, é um erro fatal
             return reject({ 
                code, 
                error: "Invalid JSON output from Python", 
                raw: stdout, 
                stderr 
            });
        }

        // Verifica flag 'ok' explícita
        if (code === 0 && parsed.ok === true) {
            resolve({ parsed, stderr });
        } else {
            reject({ 
                code, 
                error: parsed.error || "Python logical error", 
                parsed, 
                stderr 
            });
        }
      } catch (e) {
        reject({ code, stderr, raw: stdout, parseError: e?.message });
      }
    });

    // Envia dados e fecha o stdin
    p.stdin.write(JSON.stringify(payload));
    p.stdin.end();
  });
}

// --- Rotas ---

app.get("/health", (_req, res) => res.json({ ok: true, msg: "SolarScan API Online" }));

app.post("/scan", async (req, res) => {
  try {
    const payload = normalizePayload(req.body);

    // Validação de entrada
    const arr = Array.isArray(payload) ? payload : [payload];
    if (arr.length === 0) throw new Error("Payload vazio");

    for (const item of arr) {
      if (isNaN(item.lat) || isNaN(item.lon)) {
        throw new Error(`Coordenadas inválidas para ID: ${item.id}`);
      }
    }

    console.log(`🚀 Iniciando Scan para ${arr.length} subestações...`);
    const { parsed, stderr } = await runPython(payload);

    // Se houver stderr mas o código for 0, geralmente são warnings/logs do Python (logging.info)
    if (stderr && stderr.length < 2000) {
       // Opcional: Logar stderr curto no console do Node para debug
       console.log("🐍 [Python Logs]:", stderr);
    }

    res.status(200).json({
      ok: true,
      data: parsed, // Retorna a estrutura completa do runner (elapsed, zoom, results)
    });

  } catch (err) {
    console.error("❌ Erro no processamento:", err);
    res.status(500).json({
      ok: false,
      error: err.error || "Internal Server Error",
      details: err.stderr || err.message || err,
    });
  }
});

app.listen(PORT, () => {
  console.log(`✅ SolarScan API rodando em http://localhost:${PORT}`);
});