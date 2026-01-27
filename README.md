# 📋 SolarScan MVP — Documentação Técnica da Equipe

## 🎯 Visão Geral

Este repositório contém o **MVP (Minimum Viable Product)** da **SolarScan**, uma API de **inteligência geoespacial** focada em **observabilidade da rede de distribuição elétrica** por meio de **imagens de satélite** e **visão computacional**.

O objetivo principal deste MVP é disponibilizar o **esqueleto funcional do pipeline**, com **dados mockados**, permitindo que cada integrante da equipe desenvolva seu módulo de forma **independente, desacoplada e paralela**.

---

## 📁 Estrutura do Projeto

```txt
solarscan_mvp/
│
├── main.py                    # Ponto de entrada principal
├── config.py                  # Configurações globais (chaves, paths)
├── pipeline.py                # Orquestrador principal do fluxo
├── requirements.txt           # Dependências do projeto
│
├── modules/                   # Módulos do pipeline
│   ├── __init__.py
│   ├── entrada.py            # [MÓDULO 1] Validação de entrada
│   ├── geo_calculos.py       # [MÓDULO 2] Cálculos geográficos
│   ├── imagens.py            # [MÓDULO 3] Aquisição de imagens
│   ├── yolo_detection.py     # [MÓDULO 4] Detecção de painéis (YOLOv8)
│   ├── osm_integration.py    # [MÓDULO 5] Integração com OpenStreetMap
│   ├── spatial_join.py       # [MÓDULO 6] Fusão de dados geoespaciais
│   ├── analise_impacto.py    # [MÓDULO 7] Análise de impacto na rede
│   └── output_formatter.py   # [MÓDULO 8] Formatação do output
│
├── models/                   # Modelos de ML
│   └── yolo_model.py         # Placeholder para modelo YOLO
│
├── utils/                    # Utilitários auxiliares
│   └── helpers.py
│
└── tests/                    # Testes automatizados
    └── test_pipeline.py
```
---

## 📥 MÓDULO 1 — `entrada.py`  
**Validação e normalização da entrada**

Este módulo é responsável por **validar e sanitizar** a entrada recebida pela API.  
Ele garante que o pipeline só seja executado com dados geográficos válidos, evitando erros em cascata.

**Responsabilidades técnicas**
- Validar a estrutura do JSON de entrada
- Garantir presença dos campos obrigatórios (`id`, `lat`, `lon`)
- Verificar tipos (string, float)
- Validar limites geográficos (latitude e longitude)
- Normalizar dados para o formato interno do pipeline

**Por que é crítico?**  
Este módulo garante **robustez e previsibilidade**, evitando chamadas desnecessárias a APIs externas e modelos de IA com dados inválidos.

---

### 📏 MÓDULO 2 — `geo_calculos.py`  
**Cálculos geográficos e definição da área de interesse (ROI)**

Este módulo define **quanto da área ao redor da subestação será analisada**, de forma **dinâmica e estatisticamente fundamentada**.

**Responsabilidades técnicas**
- Calcular o raio de influência da subestação usando o conceito de **Vizinho Mais Próximo (Global Mean Nearest Neighbor)**
- Converter distâncias métricas (metros) para coordenadas geográficas
- Gerar um **grid de coordenadas** para varredura de imagens
- Garantir cobertura espacial adequada sem desperdício de chamadas à API de mapas

**Por que é crítico?**  
Evita varreduras “cegas” com raio fixo, reduzindo custos operacionais e garantindo **relevância estatística da amostragem espacial**.

---

### 🛰️ MÓDULO 3 — `imagens.py`  
**Aquisição de imagens de satélite**

Este módulo é responsável por obter **imagens de satélite de alta resolução** para cada ponto do grid gerado.

**Responsabilidades técnicas**
- Integrar com a **Google Maps Static API**
- Baixar imagens sob demanda
- Gerenciar erros de rede, timeout e rate limiting
- Ajustar parâmetros como zoom, resolução e formato
- Retornar imagens em memória (sem persistência local)

**Por que é crítico?**  
Este módulo conecta o mundo físico ao pipeline digital, fornecendo a matéria-prima para a visão computacional.

---

### 🤖 MÓDULO 4 — `yolo_detection.py`  
**Detecção de painéis solares com Visão Computacional**

Este módulo executa a **inferência do modelo YOLOv8**, detectando painéis solares nas imagens de satélite.

**Responsabilidades técnicas**
- Carregar o modelo YOLO (pré-treinado ou customizado)
- Pré-processar imagens (resize, normalização)
- Executar inferência em CPU
- Filtrar detecções por threshold de confiança
- Retornar coordenadas e metadados das detecções

**Por que é crítico?**  
É o **motor de inteligência visual** do SolarScan, responsável por transformar pixels em dados reais de geração distribuída.

---

### 🗺️ MÓDULO 5 — `osm_integration.py`  
**Contextualização territorial com OpenStreetMap**

Este módulo obtém o **contexto de uso do solo** da região analisada, usando dados vetoriais abertos do OpenStreetMap.

**Responsabilidades técnicas**
- Criar queries para a **Overpass API**
- Extrair polígonos de uso do solo
- Classificar áreas como residencial, comercial ou industrial
- Tratar respostas grandes e múltiplos polígonos

**Por que é crítico?**  
Permite interpretar **onde** os painéis estão instalados, adicionando contexto urbano e econômico às detecções.

---

### 🔗 MÓDULO 6 — `spatial_join.py`  
**Fusão geoespacial (Spatial Join)**

Este módulo cruza as **detecções pontuais** de painéis solares com os **polígonos de uso do solo**.

**Responsabilidades técnicas**
- Implementar lógica de point-in-polygon
- Associar cada painel detectado a um tipo de uso do solo
- Agregar resultados por categoria
- Produzir uma matriz espacial consolidada

**Por que é crítico?**  
Transforma dados brutos em **informação estruturada**, pronta para análise energética e exportação.

---

### ⚠️ MÓDULO 7 — `analise_impacto.py`  
**Análise de impacto na rede elétrica**

Este módulo interpreta os dados espaciais para estimar o **impacto da geração distribuída na rede**.

**Responsabilidades técnicas**
- Calcular métricas de penetração de MMGD
- Avaliar risco de **Duck Curve**
- Considerar diferenças entre perfis residencial, comercial e industrial
- Gerar indicadores de risco e recomendações

**Por que é crítico?**  
Conecta o pipeline técnico ao **valor estratégico para o setor elétrico**, apoiando decisões operacionais e regulatórias.

---

### 📋 MÓDULO 8 — `output_formatter.py`  
**Formatação do output da API**

Este módulo converte os dados internos em um **JSON final padronizado**, pronto para consumo por sistemas externos.

**Responsabilidades técnicas**
- Montar o schema final da resposta
- Adicionar metadados (timestamp, versão, id da subestação)
- Garantir serialização correta
- Preparar dados para integração com BI, mapas e sistemas legados

**Por que é crítico?**  
É a **interface final do SolarScan**, garantindo interoperabilidade, clareza e padronização dos dados entregues.

---

## 🔄 Resumo do Fluxo do Pipeline

```text
Entrada válida
   ↓
Cálculo do raio e grid
   ↓
Download de imagens
   ↓
Detecção de painéis (YOLO)
   ↓
Contexto territorial (OSM)
   ↓
Spatial Join
   ↓
Análise de impacto
   ↓
Output final da API
```