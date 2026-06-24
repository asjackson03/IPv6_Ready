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

## Estructura del proyecto

```
TFM/
├── .env.example
├── .gitignore
├── .dockerignore
├── README.md
├── requirements.txt
├── requirements.classifier.txt   # deps mínimas del contenedor del Módulo 2
├── Dockerfile.classifier         # imagen del Módulo 2 (ML + API)
├── docker-compose.yml            # classifier + ollama (base Módulo 3)
├── setup.py
├── main.py
├── src/
│   ├── __init__.py
│   ├── discovery/
│   │   ├── __init__.py
│   │   ├── scanner.py
│   │   ├── ipv6_checker.py
│   │   └── inventory.py
│   ├── classifier/
│   │   ├── __init__.py
│   │   ├── feature_extractor.py
│   │   ├── model_trainer.py
│   │   ├── predictor.py
│   │   └── api.py                # API REST (FastAPI) del Módulo 2
│   ├── roadmap/__init__.py
│   └── dashboard/__init__.py
├── data/
│   ├── raw/.gitkeep
│   ├── processed/.gitkeep
│   └── sample/
│       ├── mock_devices.json
│       └── training_dataset.json # dataset de entrenamiento del Módulo 2
├── tests/
│   ├── __init__.py
│   ├── test_discovery.py
│   └── test_api.py
└── docs/
    └── architecture.md
```

## Estado del desarrollo

| Módulo                 | Estado            | Descripción |
|------------------------|-------------------|-------------|
| Módulo 1 — Discovery   | ✅ Completado     | Escaneo/carga, evaluación IPv6, inventario y reporte. |
| Módulo 2 — Classifier  | ✅ Completado     | Clasificación ML (Random Forest) en LISTO/ACTUALIZABLE/REEMPLAZAR/EVALUAR + API REST (FastAPI) containerizada. |
| Módulo 3 — Roadmap     | 🔄 En desarrollo  | Hoja de ruta de migración IPv6. |
| Módulo 4 — Dashboard   | 🔄 En desarrollo  | Visualización interactiva e informes. |

## Pruebas

```bash
pytest -v
```
