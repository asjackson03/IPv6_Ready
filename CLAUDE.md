# IPv6 Ready Analyzer — Contexto del Proyecto

## Qué es esto

Prototipo de diagnóstico automatizado de compatibilidad IPv6 para infraestructuras
de red. Es el Trabajo Fin de Estudios (TFM) de Andrés para el Máster Universitario
en Transformación Digital (UNIR). Con miras a presentarse en LACNIC en octubre.

## Propósito real (más allá del académico)

La motivación no es solo cumplir un requisito de máster. Andrés es ingeniero de
redes con experiencia de campo implementando IPv6 en Colombia y LATAM, y construye
esto porque ve un patrón recurrente: las organizaciones no migran a IPv6 por
desconocimiento y miedo, no por incapacidad técnica real. Ejemplo central: el mito
de que "NAT da seguridad" — NAT nació como parche al agotamiento de IPv4, no como
mecanismo de seguridad. La herramienta busca dar un diagnóstico real y objetivo que
muestre que la infraestructura de una organización suele estar más lista de lo que
sus propios administradores creen.

## Arquitectura: 4 módulos

1. **Discovery** (`src/discovery/`) — ✅ COMPLETO. Escanea la red (Nmap real o
   mock data), evalúa compatibilidad IPv6 con heurística de reglas expertas
   (0-100 score), genera inventario JSON/CSV.
2. **Classifier** (`src/classifier/`) — 🔄 EN DESARROLLO. Clasificador ML
   (Random Forest) que categoriza dispositivos en LISTO/ACTUALIZABLE/
   REEMPLAZAR/EVALUAR. Reutiliza el ipv6_score del Módulo 1 como feature —
   los dos módulos están conectados, no son sistemas aislados.
3. **Roadmap** (`src/roadmap/`) — 📋 DISEÑADO, no implementado. LLM + RAG sobre
   datasheets de fabricantes para generar plan de migración personalizado.
4. **Dashboard** (`src/dashboard/`) — 📋 DISEÑADO, no implementado.

## Decisiones de diseño ya tomadas (no las cuestiones sin preguntar primero)

- **Heurística documentada > caja negra**: el scoring del Módulo 1 usa reglas
  expertas explícitas (ver `ipv6_checker.py`), no ML, porque la transparencia es
  un requisito en diagnóstico técnico auditable.
- **Modo demo con mock data** (`data/sample/mock_devices.json`, 10 dispositivos)
  existe para poder probar/demostrar sin acceso a red real ni privilegios root.
- **python-nmap es un wrapper, no reemplaza el binario `nmap`**: el binario
  nunca se empaqueta dentro del proyecto (licencia, multiplataforma). Se
  documenta como prerequisito del sistema.
- **Import perezoso de `nmap`**: scanner.py importa python-nmap solo dentro del
  método que lo usa, para que `--demo` funcione sin nmap instalado.
- **El proyecto vive en disco externo no-APFS**: esto genera archivos `._*`
  de macOS. El venv vive en el disco interno (`~/.venvs/ipv6-ready-analyzer/`)
  para evitar errores Unicode de pip. El `.gitignore` excluye `._*` explícitamente.
- **Perfiles de cliente diferenciados**: cliente final vs ISP requieren árboles
  de preguntas distintos (ver conversación sobre BGP, prefijos /44 vs /48,
  IPoE vs PPPoE). Esto todavía no está en código, es diseño conceptual para
  el Módulo 3 / Knowledge Base futuro.
- **Fase pre-migración vs post-despliegue**: el prototipo actual diagnostica
  redes que SOLO tienen IPv4 (esa es la realidad de los clientes objetivo).
  Herramientas como NDisc6/v6disc solo aplican una vez que ya hay IPv6 parcial
  desplegado — son para una fase de seguimiento futura, no para el diagnóstico
  inicial. No mezclar estos dos momentos en el diseño.

## Convenciones de código

- Comentarios y docstrings en español. Nombres de variables/funciones en inglés.
- Cada clase con responsabilidad única (NetworkScanner ≠ IPv6Checker ≠
  InventoryManager).
- Manejo de errores con mensajes accionables en español, sin tracebacks crudos
  hacia el usuario final (capturar en `main()`).
- Tests con pytest en `tests/test_discovery.py`, convención `test_<qué_verifica>`.

## Git / Branching

- `main` = siempre estable y demostrable.
- `develop` = integración antes de pasar a main.
- `feature/nombre-corto` o `fix/nombre-corto` = una rama por funcionalidad,
  sale de `develop`, vuelve a `develop` via merge cuando tiene tests en verde.
- Mensajes de commit con prefijo: `feat:`, `fix:`, `docs:`, `test:`.

## Estado actual (mantener esta sección actualizada en cada sesión)

- ✅ Módulo 1 completo, 4 tests pasando, validado con mock data y con escaneo
  real (red doméstica /22 de Andrés).
- 🔄 Fix en curso: timeout dinámico en `scanner.py` para que escaneos de rangos
  grandes (/22, /16) no fallen por `PortScannerError: Timeout from nmap process`.
  Incluye flag `--fast` para desactivar `-O` en redes grandes.
- 🔄 Módulo 2 (Classifier ML): prompt preparado, pendiente de ejecutar.
- 📌 TFM (documento Word): Capítulos 1, 2 y 5 redactados con la voz personal de
  Andrés (no tono genérico de paper). Estado del arte compara explícitamente
  contra Nmap, NDisc6, v6disc, SolarWinds, test-ipv6.com — posicionando el
  vacío que llena esta herramienta.

## Lo que NO hacer sin preguntar primero

- No reescribir la heurística del Módulo 1 (`ipv6_checker.py`) sin justificación
  explícita — es una decisión de diseño ya validada y documentada en el TFM.
- No empaquetar el binario de `nmap` dentro del repo.
- No mezclar lógica de "fase pre-migración" con "fase post-despliegue" en el
  mismo módulo sin separar claramente cuál es cuál.
- No tocar `mock_devices.json` (los 10 dispositivos ya están documentados tal
  cual en el TFM, capítulo 5). Si se necesita más data, crear un archivo nuevo
  (ej. `training_dataset.json`), no modificar el existente.
## Brainstorm: Arquitectura de persistencia y portal web (sesión post-Módulo 1)

Esta sección documenta decisiones de arquitectura para las fases 4 y 5 del
proyecto (base de datos y portal web), que vienen DESPUÉS de completar el
Módulo 2 (Classifier ML). No implementar nada de esto hasta que el Módulo 2
esté completo y validado.

### Por qué hace falta una base de datos

Hoy el Módulo 1 escribe a archivos planos (`data/raw/*.json`, `*.csv`). Esto
es correcto para el TFM (evidencia reproducible, fácil de anexar), pero no
permite dos cosas que sí son objetivos del proyecto:
1. Historial de escaneos para medir progreso de migración en el tiempo
   (ej. "cuántos dispositivos pasaron de INCOMPATIBLE a COMPATIBLE en 3 meses").
2. Alimentar un portal web sin acoplar el frontend directamente al filesystem.

### Esquema de datos — basado en el inventario manual real de Andrés

Andrés ya tiene un proceso de campo validado: un Excel con hojas separadas
por categoría que usa en la Fase 1 de sus proyectos reales. La base de datos
debe reflejar esas categorías, no inventar una taxonomía nueva:

- `segmentos_de_red`   — descubrible automáticamente (Nmap / Módulo 1)
- `servidores`         — descubrible automáticamente (Módulo 1)
- `equipos_red_seguridad` — descubrible automáticamente (routers, switches, firewalls)
- `equipos_finales`    — descubrible automáticamente (Módulo 1)
- `perifericos`        — descubrible automáticamente (Módulo 1, ya en mock_devices.json)
- `sedes`              — NO descubrible por red. Requiere declaración humana.
- `aplicaciones`       — NO descubrible por red. Requiere declaración humana.

Esta división (automático vs declarado) es la base de diseño del chat LLM:
el chat no es solo para generar la hoja de ruta final, es el mecanismo para
CAPTURAR sedes y aplicaciones en tiempo real durante la conversación con el
administrador de red, alimentando la base de datos directamente. Esto conecta
con el "árbol de preguntas" de levantamiento que ya se diseñó conceptualmente
(perfil cliente final vs ISP, preguntas sobre BGP/prefijos/RA).

Tablas mínimas conceptuales para soportar historial:
- `devices` (identidad persistente del equipo, no solo IP que puede cambiar)
- `scans` (cada ejecución: timestamp, target, modo --demo/--fast/etc.)
- `device_snapshots` (estado de un device en un scan específico: score, status)
- `sedes`, `aplicaciones` (declaradas vía chat)
- `conversaciones_chat` (historial de la interacción LLM con el administrador)

### Decisión tecnológica: SQLite, no Postgres (por ahora)

SQLite por ser archivo único, sin servidor separado, incluido en Python
estándar (`sqlite3`), suficiente para el volumen de un diagnóstico puntual
(no es un sistema de tráfico en tiempo real). Usar SQLAlchemy como ORM desde
el principio para que migrar a PostgreSQL en una versión multi-cliente
(post-LACNIC) sea un cambio de configuración, no una reescritura.

### Decisión tecnológica: FastAPI para la capa de API

El portal web NO debe leer la base de datos directamente. FastAPI expone
endpoints REST entre la base de datos y el portal, y es además el estándar
de facto para servir predicciones de modelos scikit-learn ya entrenados
(relevante para exponer el Módulo 2 / Classifier).

### Alcance del portal web para el TFM (no para la versión LACNIC)

Definido explícitamente por Andrés: dashboard simple de solo lectura, NO
portal multi-cliente con login/gestión compleja. Debe incluir:
- Vista de inventario por categoría (las 7 categorías del esquema arriba)
- Gráficas de compatibilidad y progreso de migración
- Chat LLM conversacional para que el administrador complete sedes y
  aplicaciones, y para responder preguntas sobre la hoja de ruta según
  la realidad detectada de su red

Andrés no tiene experiencia previa en frontend (no usar React/Vue salvo
que se decida lo contrario explícitamente). Resolver con el stack más
simple posible del lado de Python/HTML que sea compatible con buenas
prácticas — evaluar en su momento si Streamlit, Flask+Jinja, o similar,
según lo que necesite el chat interactivo y las gráficas.

### Docker — parte del roadmap de despliegue, no urgente para el TFM

Cuando exista base de datos + API + portal + dependencia del binario nmap,
"instalar el proyecto" deja de ser trivial. Docker resuelve esto empaquetando
todo en una imagen reproducible. Empaquetar nmap DENTRO de un Dockerfile
(como instrucción de instalación del sistema operativo del contenedor) es
diferente y aceptable respecto a redistribuir el binario en el repositorio
de código — no viola la misma preocupación de licencia que ya se descartó
antes. Como beneficio adicional, un contenedor Linux elimina por completo
el problema de archivos `._*` del disco externo no-APFS de macOS, porque
el filesystem del contenedor es independiente del host.

No implementar Docker todavía. Sí documentarlo en la memoria del TFM como
parte de la arquitectura de despliegue planeada.

### Orden de construcción acordado (no saltarse pasos)

1. ✅ Módulo 1 (Discovery) — completo
2. 🔄 Fix timeout dinámico en scanner.py — en curso
3. ⏭️ Módulo 2 (Classifier ML) — SIGUIENTE PASO, no desviarse de esto
4. Base de datos (SQLite + esquema de arriba)
5. Portal web + chat LLM + Docker

