"""app.py — Portal web de IPv6 Ready Analyzer (Bloque 3, Streamlit).

Dashboard de SOLO LECTURA sobre la base de datos del proyecto. Cuatro vistas:
resumen ejecutivo, topología de red, roadmap de migración y chat anclado a los
datos reales. No dispara acciones (escaneos/levantamientos/generación): esos
flujos se ejecutan desde la CLI (main.py).

Ejecutar con:  streamlit run src/portal/app.py
"""
from __future__ import annotations

import os
import sys

# Permite ejecutar `streamlit run src/portal/app.py` desde la raíz del proyecto
# resolviendo los imports `src.*` (Streamlit no agrega la raíz al path).
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.portal import data_access as da

# --------------------------------------------------------------------------- #
#  Identidad visual (coherente con el documento TFM)
# --------------------------------------------------------------------------- #
AZUL_OSCURO = "#1F4E79"
AZUL_MEDIO = "#2E75B6"
AZUL_CLARO = "#9DC3E6"

# Colores semánticos por estado IPv6 (verde→rojo según preparación).
COLOR_ESTADO = {
    "COMPATIBLE": "#2E8B57",
    "PARCIAL": "#E1A100",
    "REQUIERE_UPGRADE": "#E07B00",
    "INCOMPATIBLE": "#C0392B",
}
# Orden lógico de los estados (de más listo a menos).
ORDEN_ESTADO = ["COMPATIBLE", "PARCIAL", "REQUIERE_UPGRADE", "INCOMPATIBLE"]

COLOR_ML = {
    "LISTO": "#2E8B57",
    "ACTUALIZABLE": "#E1A100",
    "EVALUAR": "#E07B00",
    "REEMPLAZAR": "#C0392B",
}

CRITICIDAD_ICONO = {"alta": "🔴", "baja": "🟢"}


st.set_page_config(
    page_title="IPv6 Ready Analyzer",
    page_icon="🌐",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Pequeños retoques de CSS para jerarquía visual y tarjetas de métrica.
st.markdown(
    f"""
    <style>
    .main .block-container {{ padding-top: 2rem; }}
    h1, h2, h3 {{ color: {AZUL_OSCURO}; }}
    div[data-testid="stMetric"] {{
        background-color: #EAF1F8;
        border: 1px solid {AZUL_CLARO};
        border-radius: 12px;
        padding: 16px 18px;
        box-shadow: 0 1px 3px rgba(31,78,121,0.08);
    }}
    div[data-testid="stMetricValue"] {{ color: {AZUL_OSCURO}; }}
    section[data-testid="stSidebar"] {{ border-right: 1px solid {AZUL_CLARO}; }}
    .badge {{
        display:inline-block; padding:2px 10px; border-radius:10px;
        color:white; font-size:0.8rem; font-weight:600;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------- #
#  Carga de datos cacheada
# --------------------------------------------------------------------------- #
@st.cache_data(show_spinner=False)
def _scans():
    return da.listar_scans()


@st.cache_data(show_spinner=False)
def _devices(scan_id: int) -> pd.DataFrame:
    return da.devices_de_scan(scan_id)


@st.cache_data(show_spinner=False)
def _topo_sessions():
    return da.listar_topology_sessions()


@st.cache_data(show_spinner=False)
def _topo_equipos(session_id: int):
    return da.equipos_de_topology_session(session_id)


# --------------------------------------------------------------------------- #
#  Cabecera y navegación
# --------------------------------------------------------------------------- #
def cabecera() -> None:
    izq, der = st.columns([0.75, 0.25])
    with izq:
        st.title("🌐 IPv6 Ready Analyzer")
        st.caption("Diagnóstico automatizado de compatibilidad IPv6 · "
                   "Portal de resultados (solo lectura)")
    with der:
        st.markdown(
            f"<div style='text-align:right;margin-top:18px;color:{AZUL_MEDIO};"
            f"font-weight:600'>TFM · Andrés Martín</div>",
            unsafe_allow_html=True,
        )


def aviso_sin_db() -> None:
    st.warning(
        "⚠️ No se encontró la base de datos. Ejecuta primero, desde la "
        "terminal:\n\n```\npython main.py --init-db\n```",
        icon="⚠️",
    )


# --------------------------------------------------------------------------- #
#  Página 1 — Resumen ejecutivo
# --------------------------------------------------------------------------- #
def pagina_resumen() -> None:
    st.header("Resumen ejecutivo")
    scans = _scans()
    if not scans:
        st.info("No hay scans importados en la base de datos todavía.")
        return

    etiquetas = {sc["etiqueta"]: sc["id"] for sc in scans}
    elegido = st.selectbox("Escaneo a visualizar", list(etiquetas.keys()))
    scan_id = etiquetas[elegido]
    df = _devices(scan_id)
    if df.empty:
        st.info("El escaneo seleccionado no tiene dispositivos.")
        return

    total = len(df)
    n_compatible = int((df["Estado IPv6"] == "COMPATIBLE").sum())
    n_parcial = int((df["Estado IPv6"] == "PARCIAL").sum())
    n_incompat = int(df["Estado IPv6"].isin(
        ["INCOMPATIBLE", "REQUIERE_UPGRADE"]).sum())

    # Tarjetas de métricas clave.
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Dispositivos", total)
    c2.metric("Compatibles IPv6", f"{n_compatible}",
              f"{n_compatible / total * 100:.0f}% del total")
    c3.metric("Parciales", f"{n_parcial}",
              f"{n_parcial / total * 100:.0f}% del total")
    c4.metric("Incompatibles / upgrade", f"{n_incompat}",
              f"{n_incompat / total * 100:.0f}% del total",
              delta_color="inverse")

    st.divider()

    # Dos gráficas en columnas.
    g1, g2 = st.columns(2)
    with g1:
        st.subheader("Distribución por estado IPv6")
        _grafica_estado(df)
    with g2:
        st.subheader("Dispositivos por categoría y criticidad")
        _grafica_categoria(df)

    # Distribución ML si existe.
    if df["Clasificación ML"].notna().any():
        st.subheader("Clasificación del modelo ML (Módulo 2)")
        _grafica_ml(df)

    st.divider()
    st.subheader("Inventario detallado")
    st.caption("Ordenable y filtrable: haz clic en las cabeceras de columna.")
    st.dataframe(df, use_container_width=True, hide_index=True)


def _grafica_estado(df: pd.DataFrame) -> None:
    conteo = df["Estado IPv6"].value_counts().reindex(
        ORDEN_ESTADO).dropna()
    fig = go.Figure(go.Pie(
        labels=conteo.index.tolist(),
        values=conteo.values.tolist(),
        hole=0.55,
        marker=dict(colors=[COLOR_ESTADO.get(e, AZUL_MEDIO)
                            for e in conteo.index]),
        textinfo="label+percent",
    ))
    fig.update_layout(showlegend=True, height=360,
                      margin=dict(t=10, b=10, l=10, r=10))
    st.plotly_chart(fig, use_container_width=True)


def _grafica_categoria(df: pd.DataFrame) -> None:
    agrupado = df.groupby(["Categoría", "Criticidad"]).size().reset_index(
        name="Cantidad")
    fig = px.bar(
        agrupado, x="Categoría", y="Cantidad", color="Criticidad",
        color_discrete_map={"alta": "#C0392B", "baja": "#2E8B57"},
        text="Cantidad",
    )
    fig.update_layout(height=360, margin=dict(t=10, b=10, l=10, r=10),
                      xaxis_title="", legend_title="Criticidad")
    fig.update_xaxes(tickangle=-30)
    st.plotly_chart(fig, use_container_width=True)
    st.caption("🔴 alta criticidad (segmentos, servidores, equipos de red/"
               "seguridad) · 🟢 baja (periféricos, equipos finales)")


def _grafica_ml(df: pd.DataFrame) -> None:
    conteo = df["Clasificación ML"].value_counts()
    fig = px.bar(
        x=conteo.values, y=conteo.index, orientation="h",
        color=conteo.index,
        color_discrete_map=COLOR_ML,
        text=conteo.values,
    )
    fig.update_layout(height=260, showlegend=False,
                      margin=dict(t=10, b=10, l=10, r=10),
                      xaxis_title="Dispositivos", yaxis_title="")
    st.plotly_chart(fig, use_container_width=True)


# --------------------------------------------------------------------------- #
#  Página 2 — Topología de red
# --------------------------------------------------------------------------- #
def pagina_topologia() -> None:
    st.header("Topología de red (levantamiento Módulo 3a)")
    sesiones = _topo_sessions()
    if not sesiones:
        st.info("No hay sesiones de topología importadas. Ejecuta un "
                "levantamiento con `python main.py --topology` y luego "
                "`python main.py --init-db`.")
        return

    etiquetas = {s["etiqueta"]: s["id"] for s in sesiones}
    elegido = st.selectbox("Sesión de levantamiento", list(etiquetas.keys()))
    session_id = etiquetas[elegido]
    info = da.info_topology_session(session_id)
    equipos = _topo_equipos(session_id)

    c1, c2, c3 = st.columns(3)
    c1.metric("Perfil de cliente", (info.get("tipo_cliente") or "?").replace("_", " "))
    c2.metric("Sedes declaradas", info.get("cantidad_sedes") or "—")
    c3.metric("Equipos de capa 3", len(equipos))

    st.divider()
    for eq in equipos:
        _tarjeta_equipo(eq)


def _tarjeta_equipo(eq: dict) -> None:
    # El firewall complementario se muestra indentado/anidado bajo su switch
    # core (mismo criterio visual que el CLI).
    es_fw = eq.get("es_firewall_sin_capa3")
    margen = "margin-left:40px;border-left:4px solid {};".format(AZUL_CLARO) \
        if es_fw else ""
    titulo = ("↳ 🛡️ " if es_fw else "🧭 ") + str(eq.get("nombre") or "equipo")
    subtitulo = "Firewall complementario (sin capa 3)" if es_fw \
        else f"Rol lógico: {eq.get('rol_logico')}"

    with st.container():
        st.markdown(
            f"<div style='{margen}padding:6px 0 0 12px'>"
            f"<h3 style='margin-bottom:0'>{titulo}</h3>"
            f"<div style='color:{AZUL_MEDIO};font-weight:600'>{subtitulo}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Modelo", eq.get("modelo") or "—")
        col2.metric("VLANs", len(eq.get("vlans") or []))
        pol = eq.get("politicas") or {}
        col3.metric("Políticas (act./total)",
                    f"{pol.get('cantidad_activas', 0)}/"
                    f"{pol.get('cantidad_total_declaradas', 0)}")
        col4.metric("IPv6 configurado",
                    "Sí" if eq.get("ipv6_configurado") else "No")

        protocolos = (eq.get("enrutamiento") or {}).get(
            "protocolos_detectados") or []
        if protocolos:
            st.markdown("**Protocolos de enrutamiento:** " + ", ".join(protocolos))

        interfaces = eq.get("interfaces") or []
        if interfaces:
            with st.expander(f"Ver {len(interfaces)} interfaz(es)"):
                st.dataframe(pd.DataFrame(interfaces), use_container_width=True,
                             hide_index=True)

        notas = eq.get("notas") or []
        if notas:
            for n in notas:
                st.caption("⚠️ " + n)

        lic = eq.get("licencias") or {}
        if lic.get("detectadas"):
            st.info("Licencias adicionales detectadas: "
                    + (lic.get("notas") or "(sin detalle)"))
        st.divider()


# --------------------------------------------------------------------------- #
#  Página 3 — Roadmap de migración
# --------------------------------------------------------------------------- #
def pagina_roadmap() -> None:
    st.header("Roadmap de migración a IPv6")
    roadmap = da.ultimo_roadmap()
    if roadmap is None:
        st.info(
            "Todavía no se ha generado ningún roadmap.\n\n"
            "Genera uno desde la terminal con:\n\n"
            "```\npython main.py --generate-roadmap\n```\n\n"
            "(El portal es de solo lectura: no dispara la generación.)"
        )
        return

    fecha = roadmap["fecha_generacion"]
    fecha_str = fecha.strftime("%Y-%m-%d %H:%M") if fecha else "?"
    st.caption(f"Generado el {fecha_str} · roadmap #{roadmap['id']}")
    st.markdown(roadmap["contenido_markdown"])
    st.download_button(
        "⬇️ Descargar roadmap (Markdown)",
        data=roadmap["contenido_markdown"],
        file_name="roadmap_ipv6.md",
        mime="text/markdown",
    )


# --------------------------------------------------------------------------- #
#  Página 4 — Chat sobre el diagnóstico
# --------------------------------------------------------------------------- #
def pagina_chat() -> None:
    st.header("Chat sobre el diagnóstico")
    roadmap = da.ultimo_roadmap()
    if roadmap is None:
        st.warning(
            "El chat necesita un roadmap generado para anclarse a datos "
            "reales. Genera uno primero con `python main.py "
            "--generate-roadmap`. (Sin ese contexto, el asistente no "
            "responderá para evitar respuestas sin base.)"
        )
        return

    st.caption("Las respuestas se basan en el roadmap y los datos del "
               "diagnóstico; el modelo corre localmente (Ollama).")

    if "chat_historial" not in st.session_state:
        st.session_state.chat_historial = []

    for rol, texto in st.session_state.chat_historial:
        with st.chat_message(rol):
            st.markdown(texto)

    pregunta = st.chat_input("Pregunta sobre el diagnóstico o el roadmap…")
    if not pregunta:
        return

    st.session_state.chat_historial.append(("user", pregunta))
    with st.chat_message("user"):
        st.markdown(pregunta)

    with st.chat_message("assistant"):
        with st.spinner("Consultando al modelo local…"):
            respuesta = _responder_chat(pregunta, roadmap["contenido_markdown"])
        st.markdown(respuesta)
    st.session_state.chat_historial.append(("assistant", respuesta))


def _responder_chat(pregunta: str, roadmap_md: str) -> str:
    """Envía la pregunta a Ollama anclada al roadmap + resumen de la BD."""
    from src.roadmap.ollama_client import OllamaClient

    resumen_db = da.resumen_para_chat()
    prompt = (
        "Eres un asistente que responde preguntas sobre un diagnóstico de "
        "migración a IPv6 de una organización. Responde en español, de forma "
        "concreta.\n\n"
        "REGLA ESTRICTA: basa tu respuesta ÚNICAMENTE en el ROADMAP y el "
        "RESUMEN DE DATOS proporcionados abajo. Si la respuesta no está en "
        "ese contexto, dilo claramente ('No tengo ese dato en el diagnóstico "
        "actual') en vez de inventar.\n\n"
        "===== RESUMEN DE DATOS (base de datos) =====\n"
        f"{resumen_db}\n\n"
        "===== ROADMAP GENERADO =====\n"
        f"{roadmap_md}\n\n"
        f"===== PREGUNTA DEL USUARIO =====\n{pregunta}\n\n"
        "Responde ahora, fiel al contexto:"
    )
    try:
        return OllamaClient().generate_text(prompt).strip() or \
            "_(El modelo no devolvió texto.)_"
    except RuntimeError as exc:
        return f"⚠️ No se pudo consultar el modelo local: {exc}"


# --------------------------------------------------------------------------- #
#  Enrutado principal
# --------------------------------------------------------------------------- #
def main() -> None:
    cabecera()
    if not da.db_existe():
        aviso_sin_db()
        return

    st.sidebar.title("Navegación")
    pagina = st.sidebar.radio(
        "Ir a:",
        ["📊 Resumen ejecutivo", "🗺️ Topología de red",
         "🧭 Roadmap de migración", "💬 Chat sobre el diagnóstico"],
        label_visibility="collapsed",
    )
    st.sidebar.divider()
    st.sidebar.caption(
        "Portal de solo lectura. Los escaneos, levantamientos y la "
        "generación del roadmap se ejecutan desde la CLI (main.py)."
    )

    if pagina.startswith("📊"):
        pagina_resumen()
    elif pagina.startswith("🗺️"):
        pagina_topologia()
    elif pagina.startswith("🧭"):
        pagina_roadmap()
    else:
        pagina_chat()


main()
