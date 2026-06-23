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

## Estructura del proyecto

```
TFM/
├── .env.example
├── .gitignore
├── README.md
├── requirements.txt
├── setup.py
├── main.py
├── src/
│   ├── __init__.py
│   ├── discovery/
│   │   ├── __init__.py
│   │   ├── scanner.py
│   │   ├── ipv6_checker.py
│   │   └── inventory.py
│   ├── classifier/__init__.py
│   ├── roadmap/__init__.py
│   └── dashboard/__init__.py
├── data/
│   ├── raw/.gitkeep
│   ├── processed/.gitkeep
│   └── sample/mock_devices.json
├── tests/
│   ├── __init__.py
│   └── test_discovery.py
└── docs/
    └── architecture.md
```

## Estado del desarrollo

| Módulo                 | Estado            | Descripción |
|------------------------|-------------------|-------------|
| Módulo 1 — Discovery   | ✅ Completado     | Escaneo/carga, evaluación IPv6, inventario y reporte. |
| Módulo 2 — Classifier  | 🔄 En desarrollo  | Clasificación avanzada por criticidad. |
| Módulo 3 — Roadmap     | 🔄 En desarrollo  | Hoja de ruta de migración IPv6. |
| Módulo 4 — Dashboard   | 🔄 En desarrollo  | Visualización interactiva e informes. |

## Pruebas

```bash
pytest -v
```
