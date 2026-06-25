# IPv6 Ready Analyzer

## Descripción

Prototipo académico (TFE/TFM) de **diagnóstico automatizado de compatibilidad
IPv6** para redes empresariales. Descubre los dispositivos de la red, evalúa su
grado de preparación para IPv6 mediante una heurística transparente y genera un
inventario priorizado en JSON/CSV junto con un resumen ejecutivo en consola.

## Arquitectura

```
┌────────────┐   ┌────────────┐   ┌────────────┐   ┌────────────┐
│  MÓDULO 1  │──▶│  MÓDULO 2  │──▶│  MÓDULO 3  │──▶│  MÓDULO 4  │
│ DISCOVERY  │   │ CLASSIFIER │   │  ROADMAP   │   │ DASHBOARD  │
│   (✅)     │   │   (🔄)     │   │   (🔄)     │   │   (🔄)     │
├────────────┤   ├────────────┤   ├────────────┤   ├────────────┤
│ scanner    │   │ clasificar │   │ plan de    │   │ visualizar │
│ ipv6_check │   │ criticidad │   │ migración  │   │ informes   │
│ inventory  │   │            │   │            │   │            │
└────────────┘   └────────────┘   └────────────┘   └────────────┘
```

Detalle completo en [`docs/architecture.md`](docs/architecture.md).

## Requisitos previos

- **Python 3.9+** (probado en 3.12).
- **pip** y, recomendado, un entorno virtual (`venv`).
- **nmap** (binario del sistema) **solo** para escaneo de red real; no es
  necesario para el modo `--demo`.
  - macOS: `brew install nmap`
  - Debian/Ubuntu: `sudo apt install nmap`

## Instalación

```bash
# 1. Situarse en el proyecto
cd "/Volumes/Andrés Disk/8. TFM"

# 2. (Recomendado) crear y activar un entorno virtual
python3 -m venv .venv
source .venv/bin/activate          # En Windows: .venv\Scripts\activate

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. (Opcional) copiar la plantilla de configuración
cp .env.example .env
```

> **Nota (macOS + disco externo exFAT/FAT):** macOS crea archivos `._*`
> (AppleDouble) en discos no APFS/HFS+, y `pip` falla al leerlos dentro del
> `site-packages` de un `.venv` ubicado en ese disco. Si el proyecto vive en
> un disco externo, crea el entorno virtual en el disco **interno**:
>
> ```bash
> python3 -m venv ~/.venvs/ipv6-ready-analyzer
> source ~/.venvs/ipv6-ready-analyzer/bin/activate
> cd "/Volumes/Andrés Disk/8. TFM"
> pip install -r requirements.txt
> python main.py --demo
> ```

## Uso rápido

**Modo demo** (sin red real, usa `data/sample/mock_devices.json`):

```bash
python main.py --demo
```

**Escaneo de red real** (requiere nmap; `-O` suele necesitar `sudo`):

```bash
python main.py --target 192.168.1.0/24 --format both --verbose
sudo python main.py --target 192.168.1.1,192.168.1.2
```

**Rangos grandes** (p. ej. `/22`, ~1000 hosts): el timeout se calcula
dinámicamente según el número de hosts estimados, pero en rangos así de
grandes conviene usar `--fast` para evitar escaneos de varias horas:

```bash
sudo python main.py --target 10.0.0.0/22 --fast --verbose
```

> `--fast` usa `-sV --version-intensity 2` (sin `-O`), es decir, renuncia a
> la detección de sistema operativo —lo más lento del escaneo— a cambio de
> terminar mucho antes. Trade-off: menos timeout/duración, menos detalle
> (sin SO) en el inventario resultante.

Opciones principales:

| Argumento    | Descripción                                         | Por defecto |
|--------------|-----------------------------------------------------|-------------|
| `--target`   | IP, CIDR o lista separada por comas a escanear.     | —           |
| `--demo`     | Usa datos simulados sin escanear la red.            | desactivado |
| `--output`   | Directorio de salida.                               | `data/raw/` |
| `--format`   | `json`, `csv` o `both`.                             | `both`      |
| `--verbose`  | Salida detallada.                                   | desactivado |
| `--fast`     | Escaneo ligero sin `-O`, recomendado para `/22`+.   | desactivado |

Los resultados se guardan como
`data/raw/ipv6_scan_YYYYMMDD_HHMMSS.json` / `.csv`.

## Ejecución con Docker (Módulo 2 + base para Módulo 3)

El **Módulo 2** (clasificador ML) se expone como una API REST con FastAPI y se
ejecuta dentro de un contenedor para facilitar su instalación y prueba por
terceros. El `docker-compose.yml` define además el servicio **Ollama** (LLM
local), que es la **base para el Módulo 3** (parser de configuración + chat) y
que todavía **no se usa** en esta fase.

> **Importante:** el **Módulo 1** (escaneo de red con `nmap`) continúa
> ejecutándose de forma **nativa fuera de Docker**, ya que requiere acceso de
> bajo nivel a la interfaz de red del sistema operativo. Genera los archivos en
> `data/raw/`, que pueden pasarse al servicio del Módulo 2 vía el endpoint
> `/classify`.

**Prerequisito:** [Docker Desktop](https://www.docker.com/products/docker-desktop/)
instalado y en ejecución.

```bash
# Construir y levantar el servicio del Módulo 2 (clasificador).
# (El servicio ollama queda definido pero no es necesario en esta fase.)
docker-compose up --build classifier
```

**Comprobar que el Módulo 2 quedó arriba:**

```bash
curl http://localhost:8000/health
# {"status":"ok","model_loaded":false}   (false hasta entrenar el modelo)
```

**Entrenar el modelo vía API** (usa `data/sample/training_dataset.json` por
defecto; el modelo persiste en `data/processed/` gracias al volumen montado):

```bash
curl -X POST http://localhost:8000/train
# Devuelve accuracy, classification_report, matriz de confusión, etc.
```

**Clasificar dispositivos vía API** (mismo formato de salida del Módulo 1):

```bash
curl -X POST http://localhost:8000/classify \
  -H "Content-Type: application/json" \
  -d '[
        {"ip":"192.168.1.1","hostname":"rtr-core-bogota","os_detected":"Cisco IOS-XE Software","os_version":"17.6.3","device_type":"router","vendor":"Cisco","open_ports":[22,443,161],"ipv6_address":"2001:db8:100::1","ttl":255,"snmp_available":true,"firmware_version":"17.06.03","ipv6_score":95,"os_detection_method":"fingerprint"},
        {"ip":"192.168.1.2","hostname":"rtr-sucursal-medellin","os_detected":"Cisco IOS Software","os_version":"12.4(15)T","device_type":"router","vendor":"Cisco","open_ports":[23,161],"ipv6_address":null,"ttl":255,"snmp_available":true,"firmware_version":"12.4","ipv6_score":10,"os_detection_method":"fingerprint"},
        {"ip":"192.168.1.30","hostname":"cam-seguridad-lobby","os_detected":"Embedded Linux (BusyBox)","os_version":"unknown","device_type":"iot","vendor":"Generic","open_ports":[80,554],"ipv6_address":null,"ttl":64,"snmp_available":false,"firmware_version":"V5.4.5","ipv6_score":0,"os_detection_method":"ambiguo"}
      ]'
# Devuelve la lista enriquecida con ml_classification, ml_confidence,
# ml_probabilities y priority_score, ordenada por prioridad de migración.
# Si el modelo aún no está entrenado, responde HTTP 503 (no un 500 genérico).
```

**Parar los servicios:**

```bash
docker-compose down
```

## Arquitectura completa (Módulos 1–4 + Base de datos + Portal)

La entrega final integra los cuatro módulos sobre una base de datos común y un
portal web de visualización:

```
            CLI (main.py, nativo)                       Portal (Streamlit)
 ┌───────────┐  ┌───────────┐  ┌──────────────┐         ┌──────────────────┐
 │ MÓDULO 1  │  │ MÓDULO 2  │  │  MÓDULO 3     │         │   PORTAL WEB     │
 │ Discovery │  │ Classifier│  │ 3a topología  │         │  (solo lectura)  │
 │  (nmap)   │  │   (ML)    │  │ 3c roadmap    │         │  4 vistas +      │
 │           │  │           │  │ (RAG+Ollama)  │         │  chat local      │
 └─────┬─────┘  └─────┬─────┘  └──────┬───────┘         └────────┬─────────┘
       │ JSON         │ ml_*          │ topology_*.json          │ lee
       ▼              ▼               ▼                          ▼
   ┌───────────────────────────────────────────────────────────────────┐
   │            BASE DE DATOS  SQLite  (src/database/, --init-db)        │
   │  scans · devices · topology_sessions · topology_devices · roadmaps │
   └───────────────────────────────────────────────────────────────────┘
```

- **Módulo 1 (Discovery)** y **Módulo 3a (topología)** se ejecutan de forma
  nativa (acceso a red / chat interactivo) y escriben JSON en `data/`.
- **`--init-db`** importa todo ese JSON a la base de datos SQLite.
- **Módulo 3c (`--generate-roadmap`)** combina los datos de la BD con una base
  de conocimiento RAG y el LLM local (Ollama) para producir el roadmap.
- El **portal** (Módulo 4) lee la BD y presenta resumen ejecutivo, topología,
  roadmap y un chat anclado a los datos reales.

### Demo de principio a fin

```bash
# (0) Tener Ollama corriendo con el modelo (una sola vez):
docker-compose up -d ollama
docker exec -it ipv6-ollama ollama pull llama3.1:8b

# (1) Generar datos de diagnóstico (modo demo, sin red real):
python main.py --demo --train --classify

# (2) (Opcional) Levantamiento de topología guiado por IA local:
python main.py --topology

# (3) Inicializar la base de datos e importar todo lo generado:
python main.py --init-db

# (4) Generar el roadmap de migración (usa Ollama, tarda 1-2 min):
python main.py --generate-roadmap

# (5) Abrir el portal web:
streamlit run src/portal/app.py
#     → http://localhost:8501
```

> El portal también puede levantarse en contenedor: `docker-compose up --build
> portal` (lee `./data`, monta la BD generada en el paso 3 y usa el servicio
> `ollama` para el chat).

### Flags de la CLI (entrega final)

| Argumento            | Descripción                                              |
|----------------------|---------------------------------------------------------|
| `--init-db`          | Crea la BD SQLite e importa `data/raw` + `data/processed`. |
| `--generate-roadmap` | Genera el roadmap (BD + RAG + Ollama) y lo guarda en la BD. |
| `--topology`         | Levantamiento conversacional de topología (Módulo 3a).  |

## Estructura del proyecto

```
TFM/
├── .env.example
├── .gitignore
├── .dockerignore
├── README.md
├── requirements.txt
├── requirements.classifier.txt   # deps mínimas del contenedor del Módulo 2
├── requirements.portal.txt       # deps mínimas del contenedor del portal
├── Dockerfile.classifier         # imagen del Módulo 2 (ML + API)
├── Dockerfile.portal             # imagen del portal (Streamlit)
├── docker-compose.yml            # classifier + ollama + portal
├── .streamlit/config.toml        # tema visual del portal
├── setup.py
├── main.py
├── src/
│   ├── __init__.py
│   ├── discovery/                # Módulo 1
│   │   ├── scanner.py · ipv6_checker.py · inventory.py
│   ├── classifier/               # Módulo 2 (ML + API FastAPI)
│   │   ├── feature_extractor.py · model_trainer.py · predictor.py · api.py
│   ├── roadmap/                  # Módulo 3 (3a topología + 3c roadmap)
│   │   ├── command_guide.py · config_prefilter.py · ollama_client.py
│   │   ├── topology_session.py   # 3a — levantamiento conversacional
│   │   ├── rag_knowledge_base.py # 3c — recuperación RAG (TF-IDF)
│   │   └── roadmap_generator.py  # 3c — generación del roadmap
│   ├── database/                 # Base de datos (SQLite + SQLAlchemy)
│   │   ├── db.py · models.py · importer.py
│   ├── portal/                   # Portal web (Streamlit, solo lectura)
│   │   ├── app.py · data_access.py
│   └── dashboard/__init__.py
├── data/
│   ├── raw/.gitkeep              # JSON de scans (Módulo 1)
│   ├── processed/.gitkeep        # topología (3a) + modelo ML + ipv6_analyzer.db
│   └── sample/
│       ├── mock_devices.json · training_dataset.json
│       └── knowledge_base/       # corpus RAG sintético (10 fragmentos .txt)
├── tests/                        # 55 tests (pytest)
│   ├── test_discovery.py · test_api.py · test_command_guide.py
│   ├── test_config_prefilter.py · test_ollama_client.py
│   ├── test_topology_session.py · test_database.py
│   └── test_roadmap_generator.py
└── docs/architecture.md
```

## Estado del desarrollo

| Módulo                 | Estado            | Descripción |
|------------------------|-------------------|-------------|
| Módulo 1 — Discovery   | ✅ Completado     | Escaneo/carga, evaluación IPv6, inventario y reporte. |
| Módulo 2 — Classifier  | ✅ Completado     | Clasificación ML (Random Forest) en LISTO/ACTUALIZABLE/REEMPLAZAR/EVALUAR + API REST (FastAPI) containerizada. |
| Módulo 3 — Roadmap     | ✅ Completado     | 3a: levantamiento de topología con IA local (`--topology`). 3c: generación de roadmap RAG + Ollama (`--generate-roadmap`). 3b (chat de contexto perimetral): pendiente. |
| Base de datos          | ✅ Completado     | SQLite + SQLAlchemy; importa scans y topología (`--init-db`). |
| Módulo 4 — Portal      | ✅ Completado     | Dashboard Streamlit de solo lectura: resumen, topología, roadmap y chat local. |

> **Limitaciones conocidas de esta versión:** la base de conocimiento RAG usa
> fragmentos técnicos **sintéticos** escritos a mano (no datasheets reales de
> fabricantes vía PDF — queda como trabajo futuro). El Módulo 3b (chat de
> contexto perimetral/organizacional no derivable de configuración) está
> diseñado pero no implementado. El portal es de **solo lectura**: no dispara
> escaneos, levantamientos ni la generación del roadmap (eso se hace por CLI).

## Pruebas

```bash
pytest -v
```
