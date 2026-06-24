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
- ✅ Módulo 2 (Classifier ML) implementado y validado. RandomForest
  (scikit-learn 1.4.0) sobre `src/classifier/` (FeatureExtractor de 11 features,
  ModelTrainer, DeviceClassifier). Dataset `data/sample/training_dataset.json`
  (50 dispositivos, 14 LISTO / 18 ACTUALIZABLE / 12 REEMPLAZAR / 6 EVALUAR).
  Flags `--train` y `--classify` en `main.py`; resumen ML en consola y reporte
  académico en `data/processed/training_report.txt`. 18 tests en verde (13+5).
  Feature de confianza `os_confidence_score` (deriva de `os_detection_method`)
  quedó 7º de 11 en importancia con el dataset sintético — señal redundante
  aquí, hallazgo a documentar en la memoria. `ipv6_score_normalized` quedó en
  0.000 (redundante con `has_ipv6`), también citable como limitación del
  dataset sintético, no bug.
- ✅ Módulo 2 containerizado. `src/classifier/api.py` (FastAPI) expone
  `GET /`, `GET /health`, `POST /train`, `POST /classify` (503 claro si el
  modelo no está entrenado, no 500). `Dockerfile.classifier` +
  `requirements.classifier.txt` (sin nmap/pysnmp) + `docker-compose.yml`
  (servicio `classifier` con volumen `./data`; servicio `ollama` DEFINIDO
  pero sin usar todavía — base para Módulo 3). 20 tests en verde (incluye
  `tests/test_api.py` con TestClient, sin Docker). Decisión: Módulo 1 corre
  NATIVO (necesita acceso de red), Módulo 2/3 en Docker para portabilidad.
  PENDIENTE de validar por Andrés: `docker-compose up --build` (Docker no
  está instalado en la máquina de desarrollo de esta sesión; sí se validó la
  app vía TestClient en memoria y `docker-compose config` sin errores).
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

## Brainstorm: Identificación de equipos de red profesionales (firewalls/switches/routers)

Disparado por preocupación real: ¿puede la herramienta identificar correctamente
equipos de red profesionales (no solo dispositivos IoT domésticos)?

### Hallazgo de la prueba en red doméstica real (192.168.68.0/24, 23-jun-2026)
- nmap -sV -O -n SÍ entrega vendor por MAC correctamente (Roku, Samsung,
  TP-Link Systems) — esto fue un bug de parsing en _parse_host(), no
  limitación de nmap. Corregido en fix/scanner-timeout-dinamico.
- "Too many fingerprints match this host" apareció en 3 de 5 hosts reales —
  limitación REAL y documentada de fingerprinting OS pasivo en dispositivos
  de consumo con pilas TCP/IP genéricas. Buena evidencia citable para TFM
  (sección de limitaciones o estado del arte).
- Paradoja de seguridad: cuanto MEJOR configurado el firewall/equipo
  profesional (bloqueo de ICMP, probes inusuales), MÁS difícil para nmap
  hacer fingerprinting. La seguridad bien hecha es adversaria del
  descubrimiento pasivo.

### 4 vías identificadas para mejorar identificación de equipos profesionales
(en orden de impacto, ninguna implementada aún)

1. **SNMP real** (mayor impacto, brecha más clara hoy):
   mock_devices.json ya tiene snmp_available pero el NetworkScanner NO
   consulta SNMP real, solo asume el campo desde el mock. sysDescr via SNMP
   da modelo/versión exacta sin depender de fingerprinting de paquetes —
   mucho más confiable que -O para switches/routers/firewalls administrados.

2. **Banner grabbing en puertos de administración** (SSH/HTTPS):
   nmap -sV ya hace esto parcialmente (confirmado: detectó "OpenWrt uHTTPd"
   en el router doméstico real). Se puede ampliar con scripts NSE específicos
   para banners de vendors de red (Cisco, Fortinet, etc.)

3. **Chat LLM para casos ambiguos** (conecta con diseño ya existente):
   mismo patrón ya documentado para sedes/aplicaciones — si el equipo no se
   identifica con confianza, el chat le pregunta directamente al administrador
   "detecté un dispositivo en X que no pudimos identificar — ¿qué es?"

4. **Heurística ampliada de puertos+vendor sin -O**:
   _infer_device_type() ya usa puerto 9100→impresora. Ampliar: combinaciones
   de puertos (443+22+161) + vendor por MAC (Fortinet/Cisco) son altamente
   indicativos de firewall/router administrado sin necesitar fingerprint de
   OS completo vía -O.

### Decisión pendiente
Esperar resultado de prueba con 2 PCs Windows en la misma red doméstica antes
de decidir cuál de las 4 vías priorizar. NO implementar nada de esto hasta
completar Módulo 2 (ML) según orden ya acordado.


## Lección aprendida: causa real de "desconocido" en vendor/hostname

Diagnosticado 23-jun-2026. NO es un bug de parsing en _parse_host() ni
case-mismatch entre MAC y vendor dict (confirmado inspeccionando python-nmap
0.7.1 directamente: ambas claves se construyen del mismo atributo XML en la
misma iteración, nunca pueden diferir en case en esta versión de la librería).

Causa real: nmap necesita privilegios root para leer MAC address/vendor vía
ARP. Si una corrida se ejecuta sin sudo, vendor/MAC quedan como "desconocido"
aunque el host se detecte. Esto ya estaba parcialmente avisado en el mensaje
de sudo existente en scanner.py, pero antes de profundizar el diagnóstico no
era obvio que ESTA fuera la causa específica de lo que se observó en pruebas.

Se agregó normalización defensiva case-insensitive de MAC↔vendor en
_parse_host() como salvaguarda (no resuelve la causa real, pero no hace daño
y cubre el caso de un binario/versión de nmap distinto con formato de MAC
diferente).

Recalibración de timeout con datos reales de campo:
  SECONDS_PER_HOST_FULL = 4   (con -O; medido: 815s / 256 hosts ≈ 3.18s/host + margen)
  SECONDS_PER_HOST_FAST = 1   (sin -O; estimado, pendiente validar con datos reales)

Siempre verificar PRIMERO si el comando se ejecutó con sudo antes de
sospechar un bug de código cuando aparezcan campos "desconocido" en
vendor/hostname/OS.

## Criticidad por categoría (para implementar en fase de Base de Datos, NO ahora)

Disparado por: comportamiento intermitente de fingerprinting en endpoint
Windows real (.50) — un mismo dispositivo activo y conectado mostró Windows
11 identificado en una corrida y "desconocido" en otra, sin cambios de
firewall confirmados. Probable causa: no-determinismo de la pila TCP/IP de
Windows 10/11 ante probes repetidos de nmap (mitigaciones de randomización +
throttling ICMP/TCP), no un bug de nuestro código. Aceptado como limitación
conocida a documentar en el TFM, NO se va a perseguir un fix para esto.

Conclusión de arquitectura: no todos los dispositivos pesan igual en el
diagnóstico. La sección "Calidad de identificación" del CLI hoy trata todo
como lista plana — un endpoint sin identificar aparece con el mismo peso
visual que un firewall sin identificar. Esto es incorrecto y hay que
corregirlo, pero en la fase de Base de Datos (cuando se formalicen las 7
categorías del Excel de Andrés), no ahora en el CLI.

Criticidad definida (ajustada por Andrés, no es la primera propuesta):
  ALTA:
    - segmentos_de_red
    - servidores
    - equipos_red_seguridad (router, switch, firewall)
  BAJA:
    - perifericos (impresoras, cámaras)
    - equipos_finales (endpoints de usuario, DHCP, alta rotación)

Cuando se construya la BD: el resumen de calidad de identificación debe
poder filtrar/agrupar por criticidad, mostrando algo como "3 dispositivos
sin identificar — 0 son críticos (servidores/red), 3 son equipos finales
de baja prioridad" en vez de una lista plana sin jerarquía.

Nota técnica pendiente de revisar en esa misma fase: _infer_device_type()
en scanner.py también necesita revisión — varios endpoints reales
terminaron clasificados como device_type="iot" en vez de "equipo final",
lo cual rompería la lógica de criticidad si se implementara hoy sobre la
inferencia actual sin corregirla primero.

## Clarificación de arquitectura: Módulo 3 tiene 3 sub-componentes, no es solo "LLM genera roadmap"

Disparado por pregunta de Andrés: ¿cómo sabe la herramienta que un firewall
es la capa 3 real de la red (vs un switch core), si eso no es visible solo
con discovery de red (Nmap)? Respuesta: NO es parte del Módulo 2 (ML), que
solo trabaja con características de dispositivo individual (OS, puertos,
vendor) — el Módulo 2 nunca puede inferir topología/rol lógico de la red,
porque esa información no está en los datos que ve por dispositivo aislado.

Esto pertenece al Módulo 3, que en realidad tiene tres sub-componentes:

  3a. PARSER DE CONFIGURACIÓN (preferido por Andrés sobre solo cuestionario)
      El administrador sube el archivo de configuración real del equipo
      (show run de firewall/switch/router). Se parsea para extraer:
      - Topología real declarada (interfaces, rutas, VLANs)
      - Si tiene IPv6 configurado y cómo
      - Cuál es el rol lógico real (capa 3, generador de RA, etc.)
      Esto resuelve de raíz la ambigüedad de fingerprinting por red que
      causó el caso real "Sony Blu-Ray Player" — el archivo de config
      declara la verdad explícitamente, no hay que inferirla por paquetes.
      Conecta directamente con el proceso manual real que Andrés ya hace
      en campo (pedir show run + armar topología con traceroute).
      Meta explícita de Andrés: la IA local debe ser capaz de estructurar
      la topología de la red TAL COMO ESTÁ en este momento, a partir de
      estos archivos de configuración.

  3b. CHAT LLM CONVERSACIONAL
      Para todo lo que el archivo de configuración NO puede revelar:
      cuántos ISPs tiene el cliente, tipo de servicio IPoE/PPPoE si es ISP,
      criticidad de negocio de cada segmento, sedes, aplicaciones (ya
      documentado en el brainstorm de BD/portal). Complementa a 3a, no lo
      reemplaza.

  3c. GENERADOR DE ROADMAP
      Combina Módulo 1 (discovery) + Módulo 2 (clasificación ML) +
      3a (topología real) + 3b (contexto conversacional) para producir
      el plan de migración final. Este es el único sub-componente que
      coincide con la idea original simple de "LLM genera roadmap".

Orden de construcción: Módulo 2 (ML) se completa PRIMERO (ya en curso).
Módulo 3 completo (3a+3b+3c) se aborda DESPUÉS, no antes. 3a tiene prioridad
sobre 3b dentro del Módulo 3, por preferencia explícita de Andrés.

## Docker + disco externo no-APFS: nueva manifestación del problema ._*

Ya conocido: el disco externo donde vive el proyecto no es APFS, por lo
que macOS genera archivos de metadatos AppleDouble (._*) para cada archivo.
Ya resuelto para pip (venv en disco interno) y para git (.gitignore con
patrón ._*).

Nueva manifestación (23-jun-2026, construcción Docker del Módulo 2):
  docker-compose build fallaba con:
    "failed to read dockerfile: error from sender: failed to xattr
     .../._.claude: operation not permitted"
  BuildKit (el motor de build de Docker, versión 29.5.3) es más estricto
  leyendo extended attributes que versiones anteriores, y truena al
  transferir el contexto de build si encuentra estos archivos ._* en el
  disco, incluso ANTES de que .dockerignore tenga oportunidad de excluirlos
  (el error ocurre en la fase de "load build definition", previa al
  filtrado por .dockerignore).

Fix aplicado (simple, no requiere cambiar arquitectura):
  find . -name '._*' -delete
  (ejecutar desde la raíz del proyecto, antes de cada docker-compose build,
  si vuelven a aparecer estos archivos por uso normal de Finder/macOS sobre
  el disco externo)

Regla general a recordar: CUALQUIER herramienta que no sea nativamente
consciente del comportamiento de macOS en discos no-APFS (pip, git,
Docker BuildKit, y probablemente otras en el futuro) puede tropezar con
este mismo patrón de archivos ._*. La causa raíz nunca cambia: el disco
externo no es APFS. La solución de fondo sería migrar el proyecto a un
volumen APFS o al disco interno, pero se ha optado por convivir con el
problema caso por caso (venv en disco interno, .gitignore, find+delete
antes de Docker) en vez de migrar todo el proyecto, dado el costo de
tiempo de hacerlo a mitad de desarrollo.

## Infraestructura Ollama validada (24-jun-2026)

Contenedor ollama/ollama:latest corriendo vía docker-compose, modelo
llama3.1:8b descargado (~4.9GB) y funcionando. Validado con:

  curl http://localhost:11434/api/generate -d '{"model":"llama3.1:8b",
  "prompt":"...", "stream":false}'

Decisión de modelo: llama3.1:8b elegido sobre alternativas por ser
LOCAL (no "cloud" - el catálogo de Ollama en 2026 mezcla modelos
verdaderamente locales con modelos cloud de terceros que SÍ envían datos
a servidores externos, hay que verificar siempre la etiqueta antes de
elegir uno). Tamaño 8B es el punto óptimo para Mac M1 con 16GB RAM.
Alternativas de respaldo si la precisión de extracción no es suficiente:
qwen2.5:7b, phi3.5 (cambio de modelo = cambiar un string, no rediseño).

Lección de performance: primera consulta a un modelo recién cargado tarda
significativamente más por el costo de carga a memoria (load_duration),
no por la generación en sí (eval_duration). Medido: 66s totales, de los
cuales 61s fueron carga y 0.6s generación real. Las consultas siguientes,
con el modelo ya "caliente" en memoria, son mucho más rápidas. Implicación
de diseño para el parser de configuración (3a): el pre-filtrado de
10,000→~1,000 líneas que decidió Andrés no es solo optimización de costo,
es también optimización de tiempo de respuesta percibido por el usuario.

Troubleshooting de sesión: el comando `docker` dejó de reconocerse en
TODAS las terminales (VS Code, iTerm, Terminal nativa) a mitad de sesión,
aunque el binario seguía intacto en
/Applications/Docker.app/Contents/Resources/bin/docker. Causa más probable:
symlink roto en una ruta del PATH por defecto (ej. /usr/local/bin/docker),
posiblemente de una instalación anterior de Docker que Andrés mencionó
("lo instalé alguna vez pero no lo usé"). Fix aplicado: agregar la ruta
del binario directamente al PATH en ~/.zshrc:
  export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"

## Diseño completo del Módulo 3a: Parser de configuración (definido 24-jun-2026)

Diseño consolidado tras sesión de brainstorm con Andrés, basado en su
experiencia real de levantamiento en campo. Pendiente de implementar.

FLUJO COMPLETO:
1. Chat pregunta cuál equipo es la capa 3 de la red → marca y modelo
2. Chat pregunta topología perimetral: ¿hay IPS u otro dispositivo entre
   el firewall y el ISP? ¿cómo se conecta el firewall al ISP?
3. Chat indica el comando EXACTO a ejecutar según marca/modelo (reduce
   problema de 10,000→~1,000 líneas desde el origen, no por filtrado
   posterior de un archivo gigante)
4. Administrador pega el output del comando
5. Pre-filtrado determinista (regex/patrones, SIN LLM): elimina líneas
   vacías, comentarios, agrupa por bloques reconocibles
6. Bloque filtrado se pasa a Ollama (llama3.1:8b, ya validado y corriendo)
   con prompt estructurado pidiendo JSON con esquema fijo (ver abajo)
7. Chat pregunta: "¿este mismo equipo maneja también la seguridad
   (firewall) o es un equipo separado (firewall + switch core)?" -
   si es separado, vuelve al paso 1 para el segundo equipo
8. Chat pregunta si quiere agregar otro dispositivo - si sí, vuelve a 1
9. Al terminar: consolida todos los dispositivos del levantamiento en
   una sola estructura sesion_levantamiento + dispositivos[]

ESQUEMA JSON DE SALIDA (por dispositivo, dentro de dispositivos[]):
{
  "nombre_asignado": str,
  "rol_logico": str,  // "capa3_y_seguridad" | "capa3_solo" | "seguridad_solo" | etc
  "vendor_declarado": str,
  "modelo": str,
  "version_so": str,
  "licencias_adicionales": {"detectadas": bool, "notas": str},
  "interfaces": [{"nombre","ip_v4","ip_v6","vlan_id","estado"}],
  "vlans_detectadas": [int],  // = cantidad de segmentos de red
  "dhcp": {"es_servidor_dhcp": bool, "tiene_dhcp_relay": bool,
           "ip_relay_destino": str|null},
  "enrutamiento": {"protocolos_detectados": [str], "rutas_estaticas": [str],
                    "bgp_detalle": {"as_number","vecinos"}},
  "politicas": {"cantidad_total_declaradas": int, "cantidad_activas": int,
                 "cantidad_inactivas_o_deshabilitadas": int},
                 // NO incluir detalle línea por línea de cada política en
                 // esta fase - decisión explícita de Andrés, Fase I solo
                 // necesita el conteo de activas vs inactivas, no el
                 // detalle de source/destination de cada regla
  "ipv6_configurado_en_algo": bool,
  "confianza_extraccion": "alta"|"media"|"baja",
  "notas_ambiguedad": [str]
}

Nivel superior (sesion_levantamiento): fecha, tipo_cliente,
dispositivo_capa3_principal, topologia_perimetral (ips_intermedio,
conexion_isp, dispositivos_entre_firewall_e_isp)

HALLAZGO DE CAMPO QUE JUSTIFICA EL CAMPO licencias_adicionales:
Andrés reportó un caso real (1 de 15 entidades en su experiencia) donde
un switch L2 requería una licencia adicional para activar funciones L3,
y esa licencia específica NO soportaba IPv6 - hallazgo crítico que un
diagnóstico solo de hardware/OS nunca detectaría. Justifica por qué este
campo existe explícitamente en el esquema, aunque sea infrecuente.

DECISIÓN PENDIENTE para cuando se implemente: el pre-filtrado determinista
del paso 5 necesita patrones específicos por familia de vendor (Cisco usa
"!" como comentario, otros usan "#"; bloques "interface X" son bastante
universales pero la sintaxis interna varía) - esto se diseña en detalle
durante la implementación, no se ha definido el regex exacto todavía.
