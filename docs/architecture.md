# Arquitectura — IPv6 Ready Analyzer

Documento técnico del prototipo de diagnóstico automatizado de compatibilidad
IPv6 para redes empresariales. Trabajo Fin de Estudios (TFE/TFM).

---

## 1. Visión general

IPv6 Ready Analyzer descubre los dispositivos de una red, evalúa su grado de
preparación para IPv6 mediante una heurística transparente y produce un
inventario priorizado que guía la migración. El sistema se concibe en **cuatro
módulos** desacoplados; este prototipo implementa por completo el **Módulo 1
(Discovery)** y deja preparados los puntos de extensión de los otros tres.

```
                        ┌──────────────────────────────────────────────┐
                        │              IPv6 READY ANALYZER               │
                        └──────────────────────────────────────────────┘

   ┌───────────────┐     ┌────────────────┐     ┌───────────────┐     ┌───────────────┐
   │   MÓDULO 1    │     │   MÓDULO 2     │     │   MÓDULO 3    │     │   MÓDULO 4    │
   │  DISCOVERY    │────▶│  CLASSIFIER    │────▶│   ROADMAP     │────▶│  DASHBOARD    │
   │  (✅ listo)   │     │  (🔄 futuro)   │     │  (🔄 futuro)  │     │  (🔄 futuro)  │
   ├───────────────┤     ├────────────────┤     ├───────────────┤     ├───────────────┤
   │ • scanner     │     │ • clasificación│     │ • plan de     │     │ • web / TUI   │
   │ • ipv6_checker│     │   ML / reglas  │     │   migración   │     │ • gráficos    │
   │ • inventory   │     │ • criticidad   │     │ • costes      │     │ • exportación │
   └──────┬────────┘     └────────────────┘     └───────────────┘     └───────────────┘
          │
          ▼
   ┌──────────────────────────────────────────┐
   │  Red real (nmap)   ó   data/sample (demo) │
   └──────────────────────────────────────────┘
          │
          ▼
   ┌──────────────────────────────────────────┐
   │  Inventario  →  data/raw/*.json | *.csv   │
   └──────────────────────────────────────────┘
```

---

## 2. Descripción de los módulos

### Módulo 1 — Discovery (implementado)
Responsable de obtener y caracterizar los dispositivos de la red.

| Componente        | Clase             | Responsabilidad |
|-------------------|-------------------|-----------------|
| `scanner.py`      | `NetworkScanner`  | Escaneo real con nmap (`-sV -O`) o carga de datos simulados (`--demo`). |
| `ipv6_checker.py` | `IPv6Checker`     | Heurística de puntaje (0–100), estado y recomendación por dispositivo. |
| `inventory.py`    | `InventoryManager`| Construcción del DataFrame, persistencia JSON/CSV y resumen en consola. |

### Módulo 2 — Classifier (futuro)
Clasificación más fina de dispositivos (por criticidad de negocio, rol en la
red, exposición) combinando reglas y, opcionalmente, aprendizaje automático.

### Módulo 3 — Roadmap (futuro)
Generación de una hoja de ruta de migración: priorización, dependencias entre
dispositivos, estimación de esfuerzo/coste y fases de despliegue dual-stack.

### Módulo 4 — Dashboard (futuro)
Capa de visualización (web o TUI) para explorar el inventario, los puntajes y
el roadmap de forma interactiva, con exportación de informes ejecutivos.

---

## 3. Flujo de datos

```
[--target / --demo]
        │
        ▼
NetworkScanner ──► list[dict]  (dispositivos crudos + 'source')
        │
        ▼
IPv6Checker.evaluate_device ──► list[dict]  (+ ipv6_score, ipv6_status,
        │                                       recomendacion_basica, evaluated_at)
        ▼
InventoryManager.build_inventory ──► pandas.DataFrame (ordenado por score desc.)
        │
        ├──► save_results ──► data/raw/ipv6_scan_YYYYMMDD_HHMMSS.{json,csv}
        │
        └──► print_summary ──► resumen coloreado en consola
```

1. **Entrada**: el usuario elige escanear una red (`--target`) o usar datos
   simulados (`--demo`).
2. **Normalización**: el scanner devuelve dicts homogéneos con un campo
   `source` que indica el origen (`nmap_scan` o `mock_data`).
3. **Evaluación**: cada dispositivo recibe un puntaje IPv6 y un estado.
4. **Inventario**: se consolida en un DataFrame ordenado por puntaje.
5. **Salida**: persistencia en disco (JSON/CSV) y resumen ejecutivo.

---

## 4. Modelo de puntuación IPv6

El puntaje (`ipv6_score`, 0–100) es una **heurística documentada** pensada para
ser auditable y reproducible, no una métrica cerrada de proveedor.

**Base (detección de SO):**

| Sistema operativo                                   | Puntos |
|-----------------------------------------------------|:------:|
| Linux moderno (Ubuntu 20+, CentOS 8+, Debian 10+)   | 50 |
| Windows Server 2016+                                | 45 |
| Cisco IOS-XE / NX-OS                                | 45 |
| Windows Server 2012 / 2008                          | 25 |
| Cisco IOS 12.x (legacy)                             | 15 |
| SO desconocido / no clasificado                     | 20 |

**Bonificaciones:** IPv6 activo `+35`, puerto 443 `+5`, puerto 22 `+5`,
SNMP disponible `+5`.

**Penalizaciones:** dispositivo IoT `-20`, impresora de red `-15`,
firmware antiguo (familia 12.x o anterior) `-10`.

Puntaje final: `min(100, max(0, suma))`.

**Estados derivados:**

| Rango   | Estado            |
|---------|-------------------|
| 80–100  | COMPATIBLE        |
| 50–79   | PARCIAL           |
| 20–49   | REQUIERE_UPGRADE  |
| 0–19    | INCOMPATIBLE      |

---

## 5. Decisiones de diseño y justificación

- **Arquitectura modular en 4 capas.** Cada módulo tiene una responsabilidad
  única y se comunica mediante estructuras de datos simples (`list[dict]` →
  `DataFrame`). Esto permite implementar y probar el Discovery de forma
  independiente y añadir los módulos 2–4 sin reescribir el núcleo.

- **Heurística transparente en lugar de "caja negra".** En un contexto
  académico es preferible un modelo de puntaje explicable y reproducible. La
  lógica está centralizada en `IPv6Checker` y documentada en este archivo, lo
  que facilita su defensa y su evolución hacia ML en el Módulo 2.

- **Modo `--demo` con datos simulados.** El escaneo real con nmap requiere el
  binario instalado y, normalmente, privilegios de root. El modo demo
  desacopla la lógica de negocio de esos requisitos, habilita pruebas
  deterministas y permite ejecutar el prototipo en cualquier máquina.

- **Importación perezosa de `python-nmap` y ausencia de dependencia en
  `pysnmp` en el flujo demo.** Las librerías de red pueden fallar o no estar
  presentes (p. ej. `pysnmp` 4.x en Python 3.12). Importarlas solo cuando se
  usan evita que el modo demo se rompa por dependencias del escaneo real.

- **Persistencia en JSON y CSV.** JSON conserva la estructura para módulos
  posteriores; CSV facilita el análisis en hojas de cálculo. Los archivos se
  versionan por marca de tiempo para no sobrescribir ejecuciones previas.

- **`pandas` como estructura central.** Ordenar, agregar y exportar el
  inventario es trivial con DataFrames y prepara el terreno para análisis y
  visualizaciones más ricas en módulos futuros.

---

## 6. Stack tecnológico

| Componente        | Versión   | Uso |
|-------------------|-----------|-----|
| Python            | ≥ 3.9     | Lenguaje base (probado en 3.12). |
| python-nmap       | 0.7.1     | Interfaz con el binario nmap (escaneo real). |
| pysnmp            | 4.4.12    | Consultas SNMP (módulos futuros). |
| pandas            | 2.2.0     | Inventario tabular, ordenación y exportación. |
| python-dotenv     | 1.0.0     | Carga de configuración desde `.env`. |
| colorama          | 0.4.6     | Salida coloreada multiplataforma. |
| tqdm              | 4.66.1    | Barra de progreso en la evaluación. |
| tabulate          | 0.9.0     | Tablas de resumen en consola. |
| pytest            | 7.4.4     | Pruebas unitarias del Módulo 1. |
