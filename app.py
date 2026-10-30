"""Horas TIMER — registro de actividades, sueldos y reparto de carreras.

Dos pantallas en la misma dirección web:
  - EQUIPO (cada persona): la dirección normal. Registra su jornada y ve su mes.
  - ADMINISTRACIÓN: la misma dirección terminada en ?modo=admin

Para correrla en el Mac:   streamlit run app.py
Sin datos de Supabase en .streamlit/secrets.toml arranca en MODO PRUEBA LOCAL (base en este Mac).
"""
from __future__ import annotations

import base64
from datetime import date
import html
import time
from pathlib import Path

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

import servicios as sv
from motor import consolidado as cons
from motor import (
    APROBADA, BASES_REPARTO, DESCRIPCION_ESTADO, DIRECTOR, ESTADOS_EVENTO, NOMBRE_ESTADO_EVENTO,
    IVA_CHILE, PENDIENTE, PERDIDO, RECHAZADA, REALIZADO, ROLES, TECNICO, TIPOS_GASTO, Evento, Gasto, Integrante,
    ReglasReparto, desglose, horas_entre,
)
from motor.formato import DIAS_CORTOS, fecha_larga, horas_texto, nombre_mes, pesos, semanas_del_mes
from seguridad import hash_secreto, verificar_secreto

CARPETA = Path(__file__).resolve().parent
st.set_page_config(page_title="Horas TIMER", page_icon=str(CARPETA / "assets" / "icono_reloj.png"), layout="wide", initial_sidebar_state="collapsed")

MINUTOS_SESION = 60
PIN_DEMO = "2580"
CLAVE_ADMIN_LOCAL = "timer"

ESTILO = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700&family=Inter:wght@400;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
.franja { height: 6px; border-radius: 3px; margin: 0 0 .5rem 0;
  background: repeating-linear-gradient(90deg, #1B263D 0 14px, #FFFFFF 14px 28px); border: 1px solid #1B263D; }
.cabecera { display: flex; align-items: center; gap: 1rem; margin: .2rem 0 .3rem 0; }
.cabecera img { height: 46px; width: auto; }
.empresa { margin: 0; color: #ED1F24; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; font-size: .8rem; }
.titulo { font-family: 'Barlow Condensed', sans-serif; font-weight: 700; font-size: 2.4rem; margin: 0 0 .6rem 0;
  color: #1B263D; text-transform: uppercase; letter-spacing: .02em; }
.saludo { font-size: 1.4rem; font-weight: 700; margin: .2rem 0 .4rem 0; }
.aviso-local { background: #FFF3E8; border: 1px dashed #ED1F24; padding: .5rem .8rem; border-radius: 6px;
  font-size: .85rem; margin-bottom: .8rem; }
div.stButton > button, div.stFormSubmitButton > button { font-weight: 700; }
.cal { display: grid; grid-template-columns: repeat(7, 1fr); gap: 4px; max-width: 640px; }
.cal .cab { font-size: .72rem; font-weight: 700; color: #6B6F76; text-align: center; padding: 2px 0; }
.cal .dia { border: 1px solid #E3E3DF; border-radius: 6px; min-height: 58px; padding: 4px 6px; background: #fff; }
.cal .dia.vacio { background: transparent; border-color: transparent; }
.cal .dia.hoy { border: 2px solid #ED1F24; }
.cal .num { font-size: .75rem; color: #6B6F76; }
.cal .h { font-family: 'Barlow Condensed', sans-serif; font-size: 1.15rem; font-weight: 700; color: #1B263D; }
.item { border-left: 4px solid #ED1F24; background: #fff; padding: .45rem .7rem; border-radius: 4px; margin: .25rem 0; }
.item small { color: #6B6F76; }
</style>
"""


# ================================================================== base de datos
def _hay_supabase() -> bool:
    try:
        return "basedatos" in st.secrets
    except Exception:  # no existe secrets.toml
        return False


MODO_LOCAL = not _hay_supabase()


@st.cache_resource(show_spinner=False)
def motor_bd():
    if MODO_LOCAL:
        carpeta = CARPETA / "datos_local"
        carpeta.mkdir(exist_ok=True)
        motor = create_engine(f"sqlite:///{carpeta / 'timer_local.db'}",
                              connect_args={"check_same_thread": False})
        crudo = motor.raw_connection()
        try:
            crudo.executescript((CARPETA / "basedatos" / "esquema_local.sql").read_text(encoding="utf-8"))
            crudo.commit()
        finally:
            crudo.close()
    else:
        c = st.secrets["basedatos"]
        url = URL.create("postgresql+psycopg2", username=c["usuario"], password=c["contrasena"],
                         host=c["host"], port=int(c.get("puerto", 5432)), database=c.get("nombre", "postgres"))
        motor = create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=3, pool_recycle=300,
                              connect_args={"sslmode": "require", "connect_timeout": 10})
    with motor.begin() as conn:
        sv.preparar_base(conn)
        if MODO_LOCAL and not sv.lista_personas(conn):
            _cargar_personas_demo(conn)
        if MODO_LOCAL:
            _asegurar_personas_timer(conn)
    return motor


PERSONAS_TIMER = [("Stephannie Dondighual", "Administración"), ("Álvaro Cangas", "Técnico")]


def _asegurar_personas_timer(conn) -> None:
    """Modo prueba: agrega a las personas del equipo que todavía no estén (con el PIN de prueba)."""
    existentes = {(f["nombre"] or "").strip().lower() for f in sv.lista_personas(conn)}
    for nombre, cargo in PERSONAS_TIMER:
        if nombre.lower() not in existentes:
            codigo = sv.siguiente_codigo(conn)
            sv.guardar_persona(conn, {"codigo": codigo, "nombre": nombre, "cargo": cargo, "tarifa_hora": 0}, True)
            sv.asignar_pin(conn, codigo, PIN_DEMO, PIN_DEMO)


def _cargar_personas_demo(conn) -> None:
    for cod, nombre, cargo, tarifa in (("t001", "Gabriel", "Comercial / CRM", 8000),
                                       ("t002", "Pedro", "Operaciones", 7000),
                                       ("t003", "Juan Carlos", "Finanzas", 7000)):
        sv.guardar_persona(conn, {"codigo": cod, "nombre": nombre, "cargo": cargo, "tarifa_hora": tarifa}, True)
        sv.asignar_pin(conn, cod, PIN_DEMO, PIN_DEMO)


def con_bd(funcion, *args, **kwargs):
    """Ejecuta una función de servicios dentro de una transacción (todo o nada)."""
    with motor_bd().begin() as conn:
        return funcion(conn, *args, **kwargs)


@st.cache_resource(show_spinner=False)
def _hash_admin_local() -> str:
    return hash_secreto(CLAVE_ADMIN_LOCAL)


def usuarios_admin() -> dict:
    if MODO_LOCAL:
        return {"admin": {"nombre": "Administración (prueba)", "hash": _hash_admin_local()}}
    try:
        return {k: dict(v) for k, v in st.secrets["usuarios"].items()}
    except Exception:
        return {}


# ================================================================== piezas comunes
@st.cache_resource(show_spinner=False)
def logo_base64(nombre: str) -> str:
    ruta = CARPETA / "assets" / nombre
    return base64.b64encode(ruta.read_bytes()).decode("ascii") if ruta.exists() else ""


def encabezado(titulo: str, logo: str = "logo_timer.png") -> None:
    st.markdown(ESTILO, unsafe_allow_html=True)
    datos = logo_base64(logo)
    if datos:
        marca = f"<img src='data:image/png;base64,{datos}' alt='TIMER'>"
    else:
        marca = f"<p class='empresa'>{html.escape(con_bd(sv.configuracion)['nombre_empresa'])}</p>"
    st.markdown(f"<div class='franja'></div><div class='cabecera'>{marca}</div>"
                f"<h1 class='titulo'>{html.escape(titulo)}</h1>", unsafe_allow_html=True)
    if MODO_LOCAL:
        st.markdown(
            "<div class='aviso-local'><b>Modo prueba local</b>: los datos quedan solo en este computador "
            f"(carpeta <code>datos_local</code>). Personas de ejemplo con PIN <b>{PIN_DEMO}</b>; "
            f"administración: usuario <b>admin</b>, contraseña <b>{CLAVE_ADMIN_LOCAL}</b>.</div>",
            unsafe_allow_html=True)


def cambiar_modo(modo: str | None) -> None:
    if modo:
        st.query_params["modo"] = modo
    elif "modo" in st.query_params:
        del st.query_params["modo"]
    st.rerun()


def avisar(ok: bool, msg: str) -> None:
    """Guarda un mensaje para mostrarlo después de recargar la pantalla."""
    st.session_state.aviso = ("ok" if ok else "error", msg)


def aviso_pendiente() -> None:
    tipo, texto = st.session_state.pop("aviso", (None, None))
    if tipo == "ok":
        st.success(texto)
    elif tipo == "error":
        st.error(texto)


def elegir_mes(clave: str) -> tuple[int, int]:
    hoy = sv.hoy()
    opciones = []
    a, m = hoy.year, hoy.month + 1
    if m == 13:
        a, m = a + 1, 1
    for _ in range(18):
        opciones.append((a, m))
        a, m = (a, m - 1) if m > 1 else (a - 1, 12)
    return st.selectbox("Mes", opciones, index=1, format_func=lambda x: nombre_mes(*x), key=clave)


def calendario_html(anio: int, mes: int, horas: dict) -> str:
    hoy = sv.hoy()
    partes = ["<div class='cal'>"] + [f"<div class='cab'>{d}</div>" for d in DIAS_CORTOS]
    for semana in semanas_del_mes(anio, mes):
        for d in semana:
            if d is None:
                partes.append("<div class='dia vacio'></div>")
                continue
            h = horas.get(d, 0)
            intensidad = min(h / 10, 1)
            fondo = f"background: rgba(237, 31, 36, {0.08 + 0.5 * intensidad:.2f});" if h else ""
            clase = "dia hoy" if d == hoy else "dia"
            texto = f"<div class='h'>{h:g} h</div>" if h else ""
            partes.append(f"<div class='{clase}' style='{fondo}'><div class='num'>{d.day}</div>{texto}</div>")
    partes.append("</div>")
    return "".join(partes)


def opciones_categoria(cats: dict) -> list[int]:
    return sorted(cats, key=lambda i: (cats[i].grupo, cats[i].nombre))


def etiqueta_categoria(cats: dict, i: int) -> str:
    c = cats[i]
    extra = " · se paga por reparto" if not c.pagable_por_hora else ""
    return f"{c.grupo} · {c.nombre}{extra}" if c.grupo else c.nombre


def eventos_para_elegir(eventos: list) -> dict:
    """Carreras a las que se pueden cargar horas (no perdidas)."""
    return {e.id: f"{e.nombre} ({e.fecha:%d-%m-%Y})" if e.fecha else e.nombre
            for e in eventos if e.estado != PERDIDO}


# ================================================================== EQUIPO
def cerrar_sesion() -> None:
    for k in ("per_codigo", "per_nombre", "per_desde"):
        st.session_state.pop(k, None)


def pagina_equipo() -> None:
    encabezado("Registro de horas y honorarios")
    s = st.session_state
    if s.get("per_codigo") and time.time() - s.get("per_desde", 0) > MINUTOS_SESION * 60:
        cerrar_sesion()

    if not s.get("per_codigo"):
        lista = con_bd(sv.personas_para_ingresar)
        if not lista:
            st.info("Todavía no hay personas con PIN. Pídele tu PIN a la administración.")
        else:
            nombres = dict(lista)
            with st.form("ingreso"):
                codigo = st.selectbox("¿Quién eres?", options=list(nombres), index=None,
                                      format_func=lambda c: nombres[c], placeholder="Elige tu nombre")
                pin = st.text_input("Tu PIN (4 números)", type="password", max_chars=4)
                enviar = st.form_submit_button("Entrar", type="primary")
            if enviar:
                if not codigo:
                    st.error("Elige tu nombre en la lista.")
                else:
                    ok, msg = con_bd(sv.login_persona, codigo, pin.strip())
                    if ok:
                        s.per_codigo, s.per_nombre, s.per_desde = codigo, nombres[codigo], time.time()
                        st.rerun()
                    st.error(msg)
        st.write("")
        if st.button("Administración", key="ir_admin"):
            cambiar_modo("admin")
        return

    c1, c2 = st.columns([4, 1])
    c1.markdown(f"<p class='saludo'>Hola, {html.escape(s.per_nombre.split(' ')[0])}</p>", unsafe_allow_html=True)
    if c2.button("Salir", key="salir_persona"):
        cerrar_sesion()
        st.rerun()
    aviso_pendiente()
    registrar, rapida, mi_mes, resumen, consol, pagos = st.tabs(["Registro de jornada", "Carga masiva de horas",
                                                                 "Mi calendario", "Resumen de horas",
                                                                 "Consolidados y simulador", "Mis honorarios"])
    with registrar:
        pestana_registrar(s.per_codigo)
    with rapida:
        pestana_carga_rapida(s.per_codigo)
    with mi_mes:
        pestana_mi_mes(s.per_codigo)
    with resumen:
        pestana_resumen(s.per_codigo)
    with consol:
        pestana_consolidados(s.per_codigo, clave="cons_persona", autor=s.per_nombre)
    with pagos:
        pestana_mis_pagos(s.per_codigo)


def pestana_carga_rapida(codigo: str, creado_por: str = "persona") -> None:
    """Para cargar muchos días de una vez (por ejemplo, horas atrasadas desde abril)."""
    s = st.session_state
    cats = con_bd(sv.categorias, True)
    evs = eventos_para_elegir(con_bd(sv.eventos))
    etiquetas_cat = {etiqueta_categoria(cats, i): i for i in opciones_categoria(cats)}
    etiquetas_ev = {v: kk for kk, v in evs.items()}
    clave = f"lote_{creado_por}_{codigo}"

    st.markdown("Escribe una fila por actividad (puedes mezclar días). También puedes llenar la plantilla "
                "Excel y subirla. Al guardar, todo queda **por revisar**.")
    a, b = st.columns(2)
    a.download_button("Descargar plantilla Excel", data=con_bd(sv.plantilla_excel),
                      file_name="plantilla_horas_timer.xlsx", key=f"{clave}_plantilla",
                      mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    n = s.get(f"{clave}_n", 0)
    archivo = b.file_uploader("Subir planilla (Excel o CSV)", type=["xlsx", "xls", "csv"], key=f"{clave}_archivo_{n}")

    if archivo is not None and s.get(f"{clave}_firma") != (archivo.name, archivo.size):
        try:
            filas = sv.leer_planilla(archivo.getvalue(), archivo.name)
        except Exception as e:  # noqa: BLE001
            st.error(f"No pude leer la planilla ({type(e).__name__}). Revisa que tenga las columnas de la plantilla.")
            filas = None
        if filas is not None:
            por_nombre = {c.nombre.lower(): i for i, c in cats.items()}
            datos = []
            for f in filas:
                i = por_nombre.get(f["tipo"].strip().lower())
                if i is None:
                    i = next((k for k, c in cats.items() if f["tipo"].strip().lower() and
                              f["tipo"].strip().lower() in c.nombre.lower()), None)
                carrera = next((e for e in etiquetas_ev if f["carrera"] and f["carrera"].lower() in e.lower()), None)
                datos.append({"Fecha": f["fecha"], "Tipo": etiqueta_categoria(cats, i) if i else None,
                              "Descripción": f["descripcion"], "Horas": f["horas"], "Carrera": carrera,
                              "Carrera (texto)": "" if carrera else f["carrera"],
                              "Cliente": f["cliente"], "Etiqueta": f.get("etiqueta", "")})
            s[f"{clave}_inicial"] = datos
            s[f"{clave}_firma"] = (archivo.name, archivo.size)
            s[f"{clave}_version"] = s.get(f"{clave}_version", 0) + 1
            sin_tipo = sum(1 for d in datos if d["Tipo"] is None)
            st.success(f"Leí {len(datos)} filas." + (f" {sin_tipo} sin tipo reconocido: elígelo en la tabla." if sin_tipo else ""))

    inicial = s.get(f"{clave}_inicial") or [{"Fecha": None, "Tipo": None, "Descripción": "", "Horas": None,
                                             "Carrera": None, "Carrera (texto)": "", "Cliente": "", "Etiqueta": ""}]
    df = pd.DataFrame(inicial)
    df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce").dt.date
    df["Horas"] = pd.to_numeric(df["Horas"], errors="coerce")
    hoy = sv.hoy()
    editado = st.data_editor(
        df, num_rows="dynamic", width="stretch", key=f"{clave}_tabla_{s.get(f'{clave}_version', 0)}",
        column_config={
            "Fecha": st.column_config.DateColumn(format="DD/MM/YYYY", max_value=hoy, required=True),
            "Tipo": st.column_config.SelectboxColumn("Tipo de actividad", options=list(etiquetas_cat), required=True,
                                                     width="large"),
            "Descripción": st.column_config.TextColumn(width="large"),
            "Horas": st.column_config.NumberColumn(min_value=0.25, max_value=16.0, step=0.25),
            "Carrera": st.column_config.SelectboxColumn(options=list(etiquetas_ev)),
            "Carrera (texto)": st.column_config.TextColumn(
                help="Nombre de la carrera cuando todavía no está creada en «Carreras y Honorarios». "
                     "Sirve para agrupar y filtrar en Consolidados."),
            "Cliente": st.column_config.TextColumn(),
            "Etiqueta": st.column_config.TextColumn(
                help="Texto libre para clasificar (ej. «A · Fuera de carreras», «B · Coordinación de carrera»). "
                     "Las que empiezan con «B ·» o «X ·» quedan fuera del sueldo por defecto en el simulador."),
        })
    filas = [r for r in editado.to_dict("records") if _texto(r.get("Descripción")) or pd.notna(r.get("Horas"))]
    total = sum(float(r["Horas"]) for r in filas if pd.notna(r.get("Horas")))
    st.caption(f"{len(filas)} fila(s) · {horas_texto(total) if total else '0 h'} en total")
    a, b = st.columns(2)
    if a.button("Guardar todo", type="primary", key=f"{clave}_guardar", disabled=not filas):
        lote = [{"fecha": r["Fecha"] if pd.notna(r.get("Fecha")) else None,
                 "categoria_id": etiquetas_cat.get(r.get("Tipo")), "tipo": r.get("Tipo") or "",
                 "descripcion": _texto(r.get("Descripción")),
                 "horas": float(r["Horas"]) if pd.notna(r.get("Horas")) else 0,
                 "evento_id": etiquetas_ev.get(r.get("Carrera")), "cliente": _texto(r.get("Cliente")),
                 "carrera_texto": _texto(r.get("Carrera (texto)")), "etiqueta": _texto(r.get("Etiqueta"))}
                for r in filas]
        ok, msg, errores = con_bd(sv.guardar_lote, codigo, lote, creado_por)
        if ok:
            for k in [x for x in s if str(x).startswith(clave)]:
                s.pop(k, None)
            s[f"{clave}_n"] = n + 1
            avisar(True, msg)
            st.rerun()
        st.error(msg)
        for e in errores[:30]:
            st.warning(e)
    if b.button("Vaciar tabla", key=f"{clave}_vaciar"):
        for k in [x for x in s if str(x).startswith(clave)]:
            s.pop(k, None)
        s[f"{clave}_n"] = n + 1
        st.rerun()


def pestana_resumen(codigo: str | None, clave: str = "resumen") -> None:
    """Horas y valor estimado en un período (ej. desde abril hasta hoy)."""
    hoy = sv.hoy()
    a, b = st.columns(2)
    desde = a.date_input("Desde", value=date(hoy.year, 4, 1) if hoy.month >= 4 else date(hoy.year - 1, 4, 1),
                         format="DD/MM/YYYY", key=f"{clave}_desde_{codigo}")
    hasta = b.date_input("Hasta", value=hoy, format="DD/MM/YYYY", key=f"{clave}_hasta_{codigo}")
    if desde > hasta:
        st.error("La fecha «Desde» es posterior a «Hasta».")
        return
    r = con_bd(sv.resumen_periodo, codigo, desde, hasta)
    t = r["total"]
    m = st.columns(5)
    m[0].metric("Horas registradas", horas_texto(t["horas"]) if t["horas"] else "0 h")
    m[1].metric("Días con registro", t["dias"])
    m[2].metric("Aprobadas", horas_texto(t["aprobadas"]) if t["aprobadas"] else "0 h")
    m[3].metric("Por revisar", horas_texto(t["pendientes"]) if t["pendientes"] else "0 h")
    m[4].metric("Valor estimado", pesos(t["monto_total"]),
                help="Horas aprobadas y por revisar × tarifa. No incluye el reparto de carreras.")
    if t["horas_carrera"]:
        st.caption(f"Además hay {horas_texto(t['horas_carrera'])} en carreras (se pagan por reparto, no por hora).")
    if not r["meses"]:
        st.info("No hay horas registradas en este período.")
        return
    a, b = st.columns(2, gap="large")
    with a:
        st.markdown("**Por mes**")
        meses = pd.DataFrame(r["meses"])
        st.bar_chart(meses, x="Mes", y="Horas", color="#ED1F24", height=260)
        vista = meses.copy()
        vista["Valor estimado"] = vista["Valor estimado"].map(pesos)
        st.dataframe(vista, hide_index=True, width="stretch")
    with b:
        st.markdown("**Por tipo de actividad**")
        cat = pd.DataFrame(r["categorias"])
        vista = cat.copy()
        vista["Valor estimado"] = vista["Valor estimado"].map(pesos)
        st.dataframe(vista, hide_index=True, width="stretch")
    st.download_button("Descargar resumen (Excel)", key=f"{clave}_csv_{codigo}",
                       data=sv.a_csv(r["meses"], f"Resumen {desde:%d-%m-%Y} a {hasta:%d-%m-%Y} — por mes")
                       + b"\r\n" + sv.a_csv(r["categorias"], "Por tipo de actividad")[3:],
                       file_name=f"resumen_horas_{desde:%Y%m%d}_{hasta:%Y%m%d}.csv", mime="text/csv")


def pestana_registrar(codigo: str, creado_por: str = "persona") -> None:
    s = st.session_state
    hoy = sv.hoy()
    dia = st.date_input("¿Qué día trabajaste?", value=hoy, max_value=hoy, format="DD/MM/YYYY",
                        key=f"dia_{creado_por}_{codigo}")
    clave = f"{codigo}|{dia.isoformat()}"
    carritos = s.setdefault("carritos", {})
    carrito = carritos.setdefault(clave, [])

    cats = con_bd(sv.categorias, True)
    prods = con_bd(sv.productos, True)
    evs = eventos_para_elegir(con_bd(sv.eventos))

    col_form, col_carrito = st.columns([3, 2], gap="large")
    with col_form:
        st.markdown(f"**Agregar actividad — {fecha_larga(dia)}**")
        with st.form(f"agregar_{clave}", clear_on_submit=True):
            cat = st.selectbox("Tipo de actividad", opciones_categoria(cats),
                               format_func=lambda i: etiqueta_categoria(cats, i), index=None,
                               placeholder="Elige qué hiciste")
            desc = st.text_input("Descripción corta", placeholder="Ej.: llamé a 4 clientes que no cerraron")
            a, b, c = st.columns(3)
            horas = a.number_input("Horas", min_value=0.0, max_value=16.0, step=0.25, value=1.0)
            desde = b.time_input("Desde (opcional)", value=None, step=900)
            hasta = c.time_input("Hasta (opcional)", value=None, step=900)
            a, b = st.columns(2)
            prod = a.selectbox("Línea de producto", [None] + list(prods),
                               format_func=lambda i: "— (ninguna)" if i is None else prods[i])
            ev = b.selectbox("Carrera (si es para una)", [None] + list(evs),
                             format_func=lambda i: "— (ninguna)" if i is None else evs[i])
            cliente = st.text_input("Cliente (opcional)")
            agregar = st.form_submit_button("➕ Agregar al carrito", type="primary")
        st.caption("Si llenas «Desde» y «Hasta», las horas se calculan solas.")
        if agregar:
            if desde and hasta:
                horas = horas_entre(desde.strftime("%H:%M"), hasta.strftime("%H:%M")) or 0
            if cat is None:
                st.error("Elige el tipo de actividad.")
            elif not desc.strip():
                st.error("Escribe una descripción corta.")
            elif horas <= 0:
                st.error("Las horas deben ser mayores que 0.")
            else:
                carrito.append({
                    "categoria_id": cat, "descripcion": desc.strip(), "horas": float(horas),
                    "producto_id": prod, "evento_id": ev, "cliente": cliente.strip(),
                    "hora_inicio": desde.strftime("%H:%M") if desde else None,
                    "hora_fin": hasta.strftime("%H:%M") if hasta else None,
                })
                st.rerun()

    with col_carrito:
        st.markdown("**🛒 Carrito del día**")
        if not carrito:
            st.caption("Vacío. Agrega las actividades del día y después guarda la jornada.")
        for n, it in enumerate(carrito):
            x1, x2 = st.columns([5, 1])
            detalle = " · ".join(p for p in (
                prods.get(it["producto_id"]) if it["producto_id"] else "",
                evs.get(it["evento_id"]) if it["evento_id"] else "",
                it["cliente"]) if p)
            rango = f" ({it['hora_inicio']}–{it['hora_fin']})" if it["hora_inicio"] and it["hora_fin"] else ""
            x1.markdown(
                f"<div class='item'><b>{horas_texto(it['horas'])}</b>{rango} — {html.escape(cats[it['categoria_id']].nombre)}"
                f"<br>{html.escape(it['descripcion'])}<br><small>{html.escape(detalle)}</small></div>",
                unsafe_allow_html=True)
            if x2.button("✕", key=f"quitar_{clave}_{n}", help="Quitar del carrito"):
                carrito.pop(n)
                st.rerun()
        if carrito:
            total = sum(i["horas"] for i in carrito)
            st.markdown(f"**Total en el carrito: {horas_texto(total)}**")
            g1, g2 = st.columns(2)
            if g1.button("Guardar jornada", type="primary", key=f"guardar_{clave}"):
                ok, msg = con_bd(sv.guardar_jornada, codigo, dia, carrito, creado_por)
                if ok:
                    carritos.pop(clave, None)
                avisar(ok, msg)
                st.rerun()
            if g2.button("Vaciar", key=f"vaciar_{clave}"):
                carritos.pop(clave, None)
                st.rerun()

    st.divider()
    guardadas = con_bd(sv.actividades_de_dia, codigo, dia)
    st.markdown(f"**Ya guardado para este día** ({horas_texto(sum(a.horas for a in guardadas)) if guardadas else '0 h'})")
    if not guardadas:
        st.caption("Nada guardado todavía.")
    for a in guardadas:
        y1, y2 = st.columns([6, 1])
        estado = DESCRIPCION_ESTADO.get(a.estado, a.estado)
        y1.markdown(f"<div class='item'><b>{horas_texto(a.horas)}</b> — {html.escape(cats[a.categoria_id].nombre if a.categoria_id in cats else '?')}"
                    f" · <small>{estado}</small><br>{html.escape(a.descripcion)}</div>",
                    unsafe_allow_html=True)
        if a.estado == PENDIENTE or creado_por != "persona":
            with y2.popover("Editar"):
                form_editar_actividad(a, f"dia_{creado_por}", None if creado_por != "persona" else codigo)
                if st.button("🗑️ Borrar esta actividad", key=f"borrar_{a.id}"):
                    ok, msg = (con_bd(sv.anular_mi_actividad, a.id, codigo) if creado_por == "persona"
                               else con_bd(sv.anular_actividad_admin, a.id))
                    avisar(ok, msg)
                    st.rerun()


def form_editar_actividad(a, clave: str, codigo_persona: str | None = None) -> None:
    """Formulario para corregir una actividad ya guardada."""
    cats = con_bd(sv.categorias)
    prods = con_bd(sv.productos)
    evs = eventos_para_elegir(con_bd(sv.eventos))
    ids_cat = opciones_categoria(cats)
    with st.form(f"editar_{clave}_{a.id}"):
        x1, x2 = st.columns(2)
        fecha = x1.date_input("Fecha", value=a.fecha, max_value=sv.hoy(), format="DD/MM/YYYY")
        horas = x2.number_input("Horas", min_value=0.25, max_value=16.0, step=0.25, value=float(a.horas))
        cat = st.selectbox("Tipo de actividad", ids_cat, index=ids_cat.index(a.categoria_id) if a.categoria_id in ids_cat else 0,
                           format_func=lambda i: etiqueta_categoria(cats, i))
        desc = st.text_input("Descripción", value=a.descripcion)
        x1, x2, x3 = st.columns(3)
        lp = [None] + list(prods)
        prod = x1.selectbox("Producto", lp, index=lp.index(a.producto_id) if a.producto_id in lp else 0,
                            format_func=lambda i: "—" if i is None else prods[i])
        le = [None] + list(evs)
        ev = x2.selectbox("Carrera", le, index=le.index(a.evento_id) if a.evento_id in le else 0,
                          format_func=lambda i: "—" if i is None else evs[i])
        cliente = x3.text_input("Cliente", value=a.cliente)
        if st.form_submit_button("Guardar corrección", type="primary"):
            avisar(*con_bd(sv.editar_actividad, a.id, {
                "fecha": fecha, "categoria_id": cat, "horas": horas, "descripcion": desc,
                "producto_id": prod, "evento_id": ev, "cliente": cliente}, codigo_persona))
            st.rerun()


ESTADOS_TXT = {PENDIENTE: "Por revisar", APROBADA: "Aprobada", RECHAZADA: "Rechazada"}


def tabla_editable(anio: int, mes: int, codigo: str | None, modo: str) -> None:
    """Tabla tipo Excel para corregir horas ya guardadas: se edita cualquier columna y se guarda todo junto.
    modo = "persona" (solo sus actividades por revisar) o "admin" (todo, incluido el estado)."""
    filas = con_bd(sv.filas_editables, anio, mes, codigo)
    if not filas:
        st.caption("No hay actividades en este mes.")
        return
    cats = con_bd(sv.categorias)
    prods = con_bd(sv.productos)
    evs = eventos_para_elegir(con_bd(sv.eventos))
    et_cat = {i: etiqueta_categoria(cats, i) for i in opciones_categoria(cats)}
    cat_inv = {v: k for k, v in et_cat.items()}
    prod_inv = {v: k for k, v in prods.items()}
    ev_inv = {v: k for k, v in evs.items()}
    est_inv = {v: k for k, v in ESTADOS_TXT.items()}
    original = pd.DataFrame([{
        "id": f["id"], "Fecha": f["fecha"], "Persona": f["persona"], "Tipo": et_cat.get(f["categoria_id"]),
        "Descripción": f["descripcion"], "Horas": f["horas"],
        "Producto": prods.get(f["producto_id"]) if f["producto_id"] else None,
        "Carrera": evs.get(f["evento_id"]) if f["evento_id"] else None, "Cliente": f["cliente"],
        "Estado": ESTADOS_TXT.get(f["estado"], f["estado"]), "Motivo": f["motivo"], "Borrar": False,
    } for f in filas]).set_index("id")
    admin = modo == "admin"
    columnas = (["Fecha", "Persona"] if admin and codigo is None else ["Fecha"]) + \
        ["Tipo", "Descripción", "Horas", "Producto", "Carrera", "Cliente", "Estado", "Motivo", "Borrar"]
    clave = f"editable_{modo}_{codigo}_{anio}_{mes}_{st.session_state.get('version_tabla', 0)}"
    editado = st.data_editor(
        original, key=clave, hide_index=True, width="stretch", num_rows="fixed", column_order=columnas,
        disabled=["Persona"] + ([] if admin else ["Estado", "Motivo"]),
        column_config={
            "Fecha": st.column_config.DateColumn(format="DD/MM/YYYY", max_value=sv.hoy(), required=True),
            "Tipo": st.column_config.SelectboxColumn("Tipo de actividad", options=list(et_cat.values()), required=True),
            "Descripción": st.column_config.TextColumn(width="large", required=True),
            "Horas": st.column_config.NumberColumn(min_value=0.25, max_value=16.0, step=0.25, required=True),
            "Producto": st.column_config.SelectboxColumn(options=list(prods.values())),
            "Carrera": st.column_config.SelectboxColumn(options=list(evs.values())),
            "Estado": st.column_config.SelectboxColumn(options=list(ESTADOS_TXT.values()), required=True),
            "Motivo": st.column_config.TextColumn("Motivo (si se rechaza)"),
            "Borrar": st.column_config.CheckboxColumn("🗑️ Borrar"),
        })
    st.caption("Haz doble clic en una celda para cambiarla y luego aprieta «Guardar cambios». "
               + ("" if admin else "Solo puedes cambiar las que están «Por revisar»; las aprobadas las corrige administración."))

    def cambio(fila_o, fila_e, col):
        a, b = fila_o[col], fila_e[col]
        if (a is None or (not isinstance(a, str) and pd.isna(a))) and (b is None or (not isinstance(b, str) and pd.isna(b))):
            return False
        return a != b

    campos = ["Fecha", "Tipo", "Descripción", "Horas", "Producto", "Carrera", "Cliente"]
    cambios, borrar, estados = [], [], {}
    for id_, fila_e in editado.iterrows():
        fila_o = original.loc[id_]
        if bool(fila_e["Borrar"]):
            borrar.append(int(id_))
            continue
        if any(cambio(fila_o, fila_e, c) for c in campos):
            cambios.append({"id": int(id_), "fecha": fila_e["Fecha"], "categoria_id": cat_inv.get(fila_e["Tipo"]),
                            "descripcion": _texto(fila_e["Descripción"]),
                            "horas": float(fila_e["Horas"]) if pd.notna(fila_e["Horas"]) else 0,
                            "producto_id": prod_inv.get(fila_e["Producto"]), "evento_id": ev_inv.get(fila_e["Carrera"]),
                            "cliente": _texto(fila_e["Cliente"])})
        if admin and (cambio(fila_o, fila_e, "Estado") or cambio(fila_o, fila_e, "Motivo")):
            estados.setdefault((est_inv.get(fila_e["Estado"]), _texto(fila_e["Motivo"])), []).append(int(id_))
    total = len(cambios) + len(borrar) + sum(len(v) for v in estados.values())
    a, b = st.columns([1, 3])
    if a.button(f"Guardar cambios ({total})", type="primary", disabled=not total, key=f"{clave}_guardar"):
        try:
            ok, msg, _ = con_bd(sv.guardar_cambios_tabla, cambios, borrar, None if admin else codigo)
        except sv.CambiosRechazados as e:
            st.error("No se guardó nada. Corrige esto:")
            for err in e.errores:
                st.warning(err)
            return
        mensajes = [msg] if (cambios or borrar) else []
        for (estado, motivo), ids in estados.items():
            ok, m = con_bd(sv.revisar, ids, estado, st.session_state.get("admin", ""), motivo)
            mensajes.append(m)
            if not ok:
                avisar(False, " ".join(mensajes))
                st.rerun()
        avisar(True, " ".join(mensajes))
        st.session_state["version_tabla"] = st.session_state.get("version_tabla", 0) + 1
        st.rerun()
    if b.button("Descartar cambios", key=f"{clave}_descartar", disabled=not total):
        st.session_state["version_tabla"] = st.session_state.get("version_tabla", 0) + 1
        st.rerun()


def pestana_mi_mes(codigo: str) -> None:
    anio, mes = elegir_mes(f"mes_{codigo}")
    horas = con_bd(sv.horas_por_dia, codigo, anio, mes)
    filas = [f for f in con_bd(sv.sueldos_mes, anio, mes) if f.codigo == codigo]
    f = filas[0] if filas else None
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Horas cargadas", horas_texto(sum(horas.values())) if horas else "0 h")
    c2.metric("Aprobadas", horas_texto(f.horas_aprobadas) if f and f.horas_aprobadas else "0 h")
    c3.metric("Por revisar", horas_texto(f.horas_pendientes) if f and f.horas_pendientes else "0 h")
    c4.metric("Estimado bruto", pesos((f.total_bruto + f.monto_pendiente) if f else 0),
              help="Horas aprobadas y por revisar × tu tarifa, más tu parte de carreras realizadas.")
    st.markdown(calendario_html(anio, mes, horas), unsafe_allow_html=True)
    st.write("")
    st.markdown("**Mis actividades del mes** (editables)")
    tabla_editable(anio, mes, codigo, "persona")
    if f and (f.detalle_carreras or f.monto_carreras_por_aprobar):
        st.markdown("**Honorarios de carreras del mes**")
        for nombre, rol, monto in f.detalle_carreras:
            st.write(f"- ✅ {nombre} — {ROLES.get(rol.split(' – ')[0], rol)}"
                     f"{' – ' + rol.split(' – ')[1] if ' – ' in rol else ''}: {pesos(monto)}")
        if f.monto_carreras_por_aprobar:
            st.write(f"- ⏳ En aprobación: {pesos(f.monto_carreras_por_aprobar)}")


# ================================================================== ADMINISTRACIÓN
def login_admin() -> None:
    with st.form("login_admin"):
        usuario = st.text_input("Usuario").strip().lower()
        clave = st.text_input("Contraseña", type="password")
        entrar = st.form_submit_button("Entrar", type="primary")
    if entrar:
        datos = usuarios_admin().get(usuario)
        if datos is not None and verificar_secreto(clave, datos.get("hash")):
            st.session_state.admin = usuario
            st.session_state.admin_nombre = datos.get("nombre", usuario)
            st.rerun()
        time.sleep(1)
        st.error("Usuario o contraseña incorrectos.")
    if st.button("Volver"):
        cambiar_modo(None)


def pestana_aprobaciones() -> None:
    st.subheader("Horas por aprobar")
    pestana_revisar()
    st.divider()
    st.subheader("Honorarios de carreras por aprobar")
    pendientes = con_bd(sv.carreras_por_aprobar)
    if not pendientes:
        st.success("No hay honorarios de carreras por aprobar. 🎉")
        return
    st.caption("Carreras «Realizado» o «Pagado» cuyo reparto falta aprobar. Al aprobarlas, entran a la liquidación "
               "mensual y se puede pedir la boleta a cada persona.")
    nombres = con_bd(sv.personas)
    niveles = con_bd(sv.niveles_de_funciones)
    for item in pendientes:
        ev, r = item["evento"], item["reparto"]
        fecha = f" ({ev.fecha:%d-%m-%Y})" if ev.fecha else ""
        with st.expander(f"⏳ {ev.nombre}{fecha} — {pesos(item['total'])} en honorarios", expanded=len(pendientes) == 1):
            m = st.columns(4)
            m[0].metric("Margen", pesos(r.margen))
            m[1].metric("Honorarios director", pesos(r.monto_director))
            m[2].metric("Honorarios equipo", pesos(r.monto_equipo))
            m[3].metric("Resultado empresa", pesos(r.monto_empresa))
            for alerta in r.alertas:
                st.warning(alerta)
            if r.pagos:
                st.dataframe(pd.DataFrame([{
                    "Persona": nombres[p.codigo].nombre if p.codigo in nombres else p.codigo, "Rol": ROLES[p.rol],
                    "Función": p.funcion or "—", "Nivel": niveles.get(p.funcion) or "—", "Jornadas": p.peso,
                    "Ponderación": f"×{p.factor:g}", "Participación": f"{p.participacion:.1f} %",
                    "Honorario bruto": pesos(p.monto)} for p in r.pagos]), hide_index=True, width="stretch")
            a, b = st.columns([1, 3])
            if a.button("✅ Aprobar honorarios", type="primary", key=f"aprobar_hon_{ev.id}"):
                avisar(*con_bd(sv.aprobar_honorarios_carrera, ev.id, st.session_state.admin))
                st.rerun()
            b.caption("¿Algo no cuadra? Corrígelo en «Carreras y Honorarios» y vuelve aquí.")


def pestana_revisar() -> None:
    s = st.session_state
    filas = con_bd(sv.tabla_por_revisar)
    if not filas:
        st.success("No hay horas por revisar. 🎉")
        return
    df = pd.DataFrame(filas)
    st.caption(f"{len(df)} actividad(es) por revisar · {df['Horas'].sum():g} h · "
               f"{pesos(df['Valor'].sum())} si se aprueban todas. Selecciona filas haciendo clic a la izquierda.")
    vista = df.drop(columns=["id", "Estado", "Motivo"]).copy()
    vista["Valor"] = vista["Valor"].map(pesos)
    sel = st.dataframe(vista, hide_index=True, width="stretch", on_select="rerun",
                       selection_mode="multi-row", key="tabla_revisar")
    ids = [int(df.iloc[i]["id"]) for i in sel.selection.rows]
    c1, c2, c3 = st.columns(3)
    if c1.button(f"✅ Aprobar seleccionadas ({len(ids)})", disabled=not ids, type="primary"):
        avisar(*con_bd(sv.revisar, ids, APROBADA, s.admin))
        st.rerun()
    if c2.button(f"✅ Aprobar TODAS ({len(df)})"):
        avisar(*con_bd(sv.revisar, [int(x) for x in df["id"]], APROBADA, s.admin))
        st.rerun()
    with c3.popover(f"❌ Rechazar seleccionadas ({len(ids)})", disabled=not ids):
        motivo = st.text_input("Motivo (la persona lo verá)", key="motivo_rechazo")
        if st.button("Confirmar rechazo"):
            avisar(*con_bd(sv.revisar, ids, RECHAZADA, s.admin, motivo))
            st.rerun()


def pestana_sueldos() -> None:
    anio, mes = elegir_mes("mes_sueldos")
    conf = con_bd(sv.configuracion)
    ret = st.number_input("Retención boleta de honorarios (%)", min_value=0.0, max_value=100.0,
                          value=conf["pct_retencion"], step=0.25,
                          help="15,25 % es la retención 2026. Pon 0 si a alguien se le paga por contrato.")
    filas = con_bd(sv.sueldos_mes, anio, mes, ret)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total bruto", pesos(sum(f.total_bruto for f in filas)))
    c2.metric("Por horas", pesos(sum(f.monto_horas for f in filas)))
    c3.metric("Por carreras", pesos(sum(f.monto_carreras for f in filas)))
    c4.metric("Por aprobar (aún no entra)", pesos(sum(f.monto_pendiente + f.monto_carreras_por_aprobar for f in filas)),
              help="Horas por revisar y honorarios de carreras por aprobar. Se aprueban en «Aprobaciones».")
    tabla = sv.filas_sueldo_tabla(filas)
    if not tabla:
        st.info("No hay horas ni carreras realizadas en este mes.")
        return
    vista = pd.DataFrame(tabla)
    for col in ("Tarifa/h", "Pago horas", "Pago carreras", "Total bruto", "Retención", "Total líquido",
                "Monto por revisar"):
        vista[col] = vista[col].map(pesos)
    st.dataframe(vista, hide_index=True, width="stretch")
    for f in filas:
        if f.alertas or f.detalle_carreras:
            with st.expander(f"{f.nombre}: detalle y avisos"):
                for nombre, rol, monto in f.detalle_carreras:
                    st.write(f"- {nombre} — {ROLES.get(rol, rol)}: {pesos(monto)}")
                for a in f.alertas:
                    st.warning(a)
    pendientes = con_bd(sv.carreras_pendientes_del_mes, anio, mes)
    if pendientes:
        st.info("Carreras de este mes que aún no están marcadas como «Realizado» (no entran al sueldo): "
                + ", ".join(e.nombre for e in pendientes))
    st.download_button("Descargar sueldos del mes (Excel)", data=sv.a_csv(tabla, f"Sueldos {nombre_mes(anio, mes)}"),
                       file_name=f"sueldos_{anio}_{mes:02d}.csv", mime="text/csv")


def pestana_analisis() -> None:
    anio, mes = elegir_mes("mes_analisis")
    datos = con_bd(sv.analisis_mes, anio, mes)
    st.metric("Horas del mes (sin rechazadas)", horas_texto(datos["total"]) if datos["total"] else "0 h")
    if not datos["total"]:
        st.info("Sin horas cargadas este mes.")
        return
    c1, c2 = st.columns(2)
    for col, titulo in ((c1, "Por persona"), (c2, "Por grupo"), (c1, "Por categoría"), (c2, "Por producto")):
        with col:
            st.markdown(f"**{titulo}**")
            df = pd.DataFrame({"Nombre": list(datos[titulo]), "Horas": list(datos[titulo].values())})
            st.bar_chart(df, x="Nombre", y="Horas", horizontal=True, color="#ED1F24",
                         height=max(160, 34 * len(df)))
    st.divider()
    st.markdown("**Todas las actividades del mes**")
    pers = con_bd(sv.personas)
    quien = st.selectbox("Persona", [None] + list(pers), format_func=lambda c: "Todas" if c is None else pers[c].nombre)
    tabla_editable(anio, mes, quien, "admin")
    tabla = con_bd(sv.tabla_mes, anio, mes, quien)
    if tabla:
        st.download_button("Descargar actividades (Excel)", data=sv.a_csv(tabla, f"Actividades {nombre_mes(anio, mes)}"),
                           file_name=f"actividades_{anio}_{mes:02d}.csv", mime="text/csv")


# ------------------------------------------------------------------ consolidados y simulador
ATAJOS_PERIODO = ("Este año", "Este trimestre", "Este mes", "Esta semana", "Personalizado")


def _rango_atajo(atajo: str, hoy: date) -> tuple[date, date]:
    from datetime import timedelta
    if atajo == "Este trimestre":
        return date(hoy.year, 3 * ((hoy.month - 1) // 3) + 1, 1), hoy
    if atajo == "Este mes":
        return date(hoy.year, hoy.month, 1), hoy
    if atajo == "Esta semana":
        return hoy - timedelta(days=hoy.weekday()), hoy
    return date(hoy.year, 1, 1), hoy


def _fuera_por_defecto(filas: list) -> dict:
    etiquetas = {cons.texto_dim(f, "etiqueta") for f in filas}
    return {"etiqueta": sorted(e for e in etiquetas if cons.excluida_por_defecto(e))}


def pestana_consolidados(codigo: str | None, clave: str = "cons", autor: str = "") -> None:
    """Horas por día / semana / mes / trimestre / año, y simulador: qué entra al sueldo y cuánto da, en vivo."""
    s = st.session_state
    k = f"{clave}_{codigo or 'todos'}"
    hoy = sv.hoy()
    conf = con_bd(sv.configuracion)

    # Cargar un escenario guardado (se aplica antes de dibujar los filtros)
    pendiente = s.pop(f"{k}_cargar", None)
    if pendiente is not None:
        par = pendiente["parametros"]
        s[f"{k}_atajo"] = "Personalizado"
        s[f"{k}_desde"] = date.fromisoformat(par.get("desde", f"{hoy.year}-01-01"))
        s[f"{k}_hasta"] = date.fromisoformat(par.get("hasta", hoy.isoformat()))
        s[f"{k}_tarifa"] = float(par.get("tarifa") or 0)
        s[f"{k}_ret"] = float(par.get("retencion", 15.25))
        for campo in cons.DIMENSIONES.values():
            s[f"{k}_fuera_{campo}"] = list(par.get("fuera", {}).get(campo, []))
        s[f"{k}_manual"] = {int(i): bool(v) for i, v in par.get("manual", {}).items()}
        s[f"{k}_ok"] = f"Cargué el escenario «{pendiente['nombre']}»."
    if s.pop(f"{k}_reiniciar", False):
        for campo in cons.DIMENSIONES.values():
            s.pop(f"{k}_fuera_{campo}", None)
        s.pop(f"{k}_manual", None)
        s[f"{k}_todo"] = s.pop(f"{k}_pedir_todo", False)
    if s.get(f"{k}_ok"):
        st.success(s.pop(f"{k}_ok"))

    st.markdown("Junta tus horas en el período que quieras y **elige qué entra al sueldo**: "
                "el total se recalcula al instante. Guarda cada versión como escenario para comparar "
                "(ej. «Mi propuesta» vs «Feedback JC»).")
    a, b, c = st.columns([3, 1.3, 1.3])
    with a:
        atajo = st.segmented_control("Período", ATAJOS_PERIODO, key=f"{k}_atajo",
                                     **({} if f"{k}_atajo" in s else {"default": "Este año"})) or "Este año"
    if atajo == "Personalizado":
        desde = b.date_input("Desde", format="DD/MM/YYYY", key=f"{k}_desde",
                             **({} if f"{k}_desde" in s else {"value": date(hoy.year, 1, 1)}))
        hasta = c.date_input("Hasta", format="DD/MM/YYYY", key=f"{k}_hasta",
                             **({} if f"{k}_hasta" in s else {"value": hoy}))
    else:
        desde, hasta = _rango_atajo(atajo, hoy)
        b.caption(f"Desde **{desde:%d-%m-%Y}**")
        c.caption(f"Hasta **{hasta:%d-%m-%Y}**")
    if desde > hasta:
        st.error("La fecha «Desde» es posterior a «Hasta».")
        return

    filas = con_bd(sv.filas_consolidado, codigo, desde, hasta)
    if not filas:
        st.info("No hay horas registradas en este período.")
        return

    pers = con_bd(sv.personas)
    tarifa_base = pers[codigo].tarifa_hora if codigo and codigo in pers and pers[codigo].tarifa_hora else 25000.0
    a, b, c, d = st.columns(4)
    periodo = a.selectbox("Ver por", cons.PERIODOS, index=2, key=f"{k}_periodo")
    dimension = b.selectbox("Agrupar por", list(cons.DIMENSIONES), index=0, key=f"{k}_dim")
    tarifa = c.number_input("Tarifa por hora (CLP)", min_value=0.0, step=1000.0, format="%.0f",
                            key=f"{k}_tarifa", **({} if f"{k}_tarifa" in s else {"value": float(tarifa_base)}),
                            help="Cámbiala para ver cómo cambia el número. Con 0 se usa la tarifa de cada persona "
                                 "y de cada tipo de actividad.")
    ret = d.number_input("Retención boleta (%)", min_value=0.0, max_value=100.0, step=0.25,
                         key=f"{k}_ret", **({} if f"{k}_ret" in s else {"value": float(conf.get("pct_retencion") or 15.25)}))
    tarifa_sim = tarifa or None

    # ---- qué entra al sueldo
    st.markdown("##### ¿Qué entra al sueldo?")
    defecto = {} if s.get(f"{k}_todo") else _fuera_por_defecto(filas)
    fuera: dict[str, set] = {}
    filtros = (("etiqueta", "Etiquetas"), ("carrera", "Carreras"), ("categoria", "Tipos de actividad"),
               ("estado", "Estado"))
    columnas = st.columns(len(filtros))
    for col, (campo, titulo) in zip(columnas, filtros):
        opciones = sorted({cons.texto_dim(f, campo) for f in filas}, key=lambda x: (x == cons.SIN_DATO, x))
        clave_ms = f"{k}_fuera_{campo}"
        if clave_ms in s:
            s[clave_ms] = [x for x in s[clave_ms] if x in opciones]
        elegidas = col.multiselect(f"Dejar fuera: {titulo.lower()}", opciones, key=clave_ms,
                                   default=None if clave_ms in s else [x for x in defecto.get(campo, []) if x in opciones],
                                   placeholder="Nada fuera")
        fuera[campo] = set(elegidas)
    if defecto.get("etiqueta") and not s.get(f"{k}_todo"):
        st.caption("Por defecto quedan fuera las etiquetas que empiezan con «B ·» (coordinación que se paga en la "
                   "boleta de la carrera) y «X ·» (no cobrar). Puedes cambiarlo arriba.")
    b1, b2, _ = st.columns([1.2, 1.2, 3])
    if b1.button("Incluir todo", key=f"{k}_btn_todo"):
        s[f"{k}_reiniciar"], s[f"{k}_pedir_todo"] = True, True
        st.rerun()
    if b2.button("Volver a lo sugerido", key=f"{k}_btn_sug"):
        s[f"{k}_reiniciar"] = True
        st.rerun()

    manual: dict = s.setdefault(f"{k}_manual", {})
    base = cons.incluidas_por_filtros(filas, fuera)
    resumen = st.container()

    with st.expander(f"Elegir actividad por actividad ({len(filas)} registros)", expanded=False):
        st.caption("Marca o desmarca la casilla «Entra». Lo que marques aquí manda sobre los filtros de arriba.")
        incl_actual = cons.incluidas_por_filtros(filas, fuera, manual)
        df = pd.DataFrame([{
            "id": f["id"], "Entra": f["id"] in incl_actual, "Fecha": f["fecha"], "Tipo": f["categoria"],
            "Descripción": f["descripcion"], "Horas": f["horas"], "Carrera": f["carrera"], "Etiqueta": f["etiqueta"],
            "Persona": f["persona"], "Valor": pesos(cons.valor_fila(f, tarifa_sim)),
        } for f in sorted(filas, key=lambda x: (x["fecha"], x["id"]))])
        firma = abs(hash((repr(sorted((c, tuple(sorted(v))) for c, v in fuera.items())), repr(sorted(manual.items())),
                          desde, hasta, tarifa)))
        orden = ["Entra", "Fecha", "Tipo", "Descripción", "Horas", "Carrera", "Etiqueta", "Valor"]
        if codigo is None:
            orden.insert(2, "Persona")
        editado = st.data_editor(
            df, hide_index=True, width="stretch", num_rows="fixed", key=f"{k}_ed_{firma}", column_order=orden,
            disabled=[c for c in df.columns if c != "Entra"], height=min(420, 38 + 35 * len(df)),
            column_config={"Entra": st.column_config.CheckboxColumn(width="small"),
                           "Fecha": st.column_config.DateColumn(format="DD/MM/YYYY"),
                           "Descripción": st.column_config.TextColumn(width="large"),
                           "Horas": st.column_config.NumberColumn(format="%.2f")})
        for r in editado.to_dict("records"):
            i, entra = int(r["id"]), bool(r["Entra"])
            if entra == (i in base):
                manual.pop(i, None)
            else:
                manual[i] = entra
    incluidas = cons.incluidas_por_filtros(filas, fuera, manual)
    tot = cons.totales(filas, incluidas, tarifa_sim, ret, desde, hasta)

    with resumen:
        m = st.columns(5)
        m[0].metric("Horas que entran", horas_texto(tot["horas"]) if tot["horas"] else "0 h",
                    delta=f"-{horas_texto(tot['horas_fuera'])} fuera" if tot["horas_fuera"] else None,
                    delta_color="off")
        m[1].metric("Valor bruto", pesos(tot["bruto"]))
        m[2].metric("Líquido", pesos(tot["liquido"]), help=f"Bruto menos retención {ret:g} % ({pesos(tot['retencion'])}).")
        m[3].metric("Boleta mensual equivalente", pesos(tot["bruto_mes"]),
                    help=f"Bruto dividido por los {tot['meses_periodo']:.1f} meses del período. "
                         f"Si solo cuentas los {tot['meses_activos']} meses con actividad: {pesos(tot['bruto_mes_activo'])}.")
        m[4].metric("Horas por semana", f"{tot['horas_semana']:.1f} h",
                    help=f"Promedio del período. Por mes: {tot['horas_mes']:.1f} h.")
        if tot["horas_fuera"]:
            st.caption(f"De {horas_texto(tot['horas_todo'])} registradas quedan fuera {horas_texto(tot['horas_fuera'])} "
                       f"({pesos(tot['bruto_todo'] - tot['bruto'])} bruto).")

    if not incluidas:
        st.warning("Con estos filtros no entra ninguna actividad.")
        return

    # ---- consolidado
    st.markdown(f"##### Consolidado por {periodo.lower()} y {dimension.lower()}")
    largas = cons.por_periodo(filas, incluidas, periodo, dimension, tarifa_sim)
    orden_periodos = list(dict.fromkeys(x["Período"] for x in largas))
    try:
        import altair as alt
        graf = alt.Chart(pd.DataFrame(largas)).mark_bar().encode(
            x=alt.X("Período:N", sort=orden_periodos, title=None),
            y=alt.Y("sum(Horas):Q", title="Horas"),
            color=alt.Color(f"{dimension}:N", legend=alt.Legend(orient="bottom", columns=3, title=None)),
            tooltip=["Período", dimension, alt.Tooltip("sum(Horas):Q", title="Horas", format=".2f")],
        ).properties(height=300)
        try:
            st.altair_chart(graf, width="stretch")
        except TypeError:  # versiones antiguas de Streamlit
            st.altair_chart(graf, use_container_width=True)
    except ImportError:
        st.bar_chart(pd.DataFrame(largas), x="Período", y="Horas", color=dimension)
    cols, cruz = cons.tabla_cruzada(filas, incluidas, periodo, dimension, tarifa_sim)
    vista = pd.DataFrame(cruz)
    vista["Valor"] = vista["Valor"].map(pesos)
    st.dataframe(vista, hide_index=True, width="stretch",
                 column_config={c: st.column_config.NumberColumn(format="%.2f") for c in [*cols, "Total horas"]})

    st.markdown(f"##### Cuánto toma cada tarea ({dimension.lower()})")
    est = pd.DataFrame(cons.estadistica(filas, incluidas, dimension, tarifa_sim))
    est["Valor"] = est["Valor"].map(pesos)
    st.dataframe(est, hide_index=True, width="stretch", column_config={
        c: st.column_config.NumberColumn(format="%.2f") for c in ("Horas", "Promedio por registro", "Mediana", "Máximo")}
        | {"% del total": st.column_config.ProgressColumn(format="%.0f %%", min_value=0, max_value=100)})
    st.caption("Promedio y mediana = horas por registro. Sirven para estimar cuánto toma, por ejemplo, una cotización "
               "o una reunión, y armar un horario y una boleta fija.")

    # ---- escenarios
    st.markdown("##### Escenarios")
    guardados = con_bd(sv.escenarios, codigo)
    comparacion = [{"Escenario": "Lo que ves ahora", "Horas": tot["horas"], "Bruto": tot["bruto"],
                    "Líquido": tot["liquido"], "Diferencia": 0.0}]
    for e in guardados:
        par = e["parametros"]
        fuera_e = {c: set(v) for c, v in par.get("fuera", {}).items()}
        man_e = {int(i): bool(v) for i, v in par.get("manual", {}).items()}
        inc_e = cons.incluidas_por_filtros(filas, fuera_e, man_e)
        t_e = cons.totales(filas, inc_e, par.get("tarifa") or None, par.get("retencion", ret))
        comparacion.append({"Escenario": e["nombre"], "Horas": t_e["horas"], "Bruto": t_e["bruto"],
                            "Líquido": t_e["liquido"], "Diferencia": t_e["bruto"] - tot["bruto"]})
    if guardados:
        vista = pd.DataFrame(comparacion)
        for c in ("Bruto", "Líquido", "Diferencia"):
            vista[c] = vista[c].map(pesos)
        st.dataframe(vista, hide_index=True, width="stretch",
                     column_config={"Horas": st.column_config.NumberColumn(format="%.2f")})
        st.caption("Cada escenario se recalcula con las fechas que estás viendo ahora.")
    a, b = st.columns([3, 1])
    nombre = a.text_input("Nombre del escenario", key=f"{k}_nombre_esc",
                          placeholder="Ej.: Mi propuesta · Sin Speed Lab · Feedback JC")
    b.write("")
    if b.button("Guardar escenario", key=f"{k}_guardar_esc", type="primary"):
        parametros = {"desde": desde.isoformat(), "hasta": hasta.isoformat(), "tarifa": tarifa, "retencion": ret,
                      "fuera": {c: sorted(v) for c, v in fuera.items() if v},
                      "manual": {str(i): v for i, v in manual.items()}}
        ok, msg = con_bd(sv.guardar_escenario, nombre, codigo, parametros,
                         {f["id"] for f in filas} - incluidas, autor or "persona")
        avisar(ok, msg)
        if ok:
            st.rerun()
        st.error(msg)
    if guardados:
        a, b, c = st.columns([3, 1, 1])
        por_id = {e["id"]: e for e in guardados}
        elegido = a.selectbox("Escenario guardado", list(por_id), key=f"{k}_esc_sel",
                              format_func=lambda i: f"{por_id[i]['nombre']} · {por_id[i]['creado_en']}")
        b.write("")
        c.write("")
        if b.button("Cargar", key=f"{k}_esc_cargar"):
            s[f"{k}_cargar"] = por_id[elegido]
            st.rerun()
        if c.button("Borrar", key=f"{k}_esc_borrar"):
            ok, msg = con_bd(sv.borrar_escenario, elegido)
            avisar(ok, msg)
            st.rerun()

    nombre_persona = pers[codigo].nombre if codigo and codigo in pers else "Equipo TIMER"
    st.download_button(
        "Descargar consolidado (Excel)", key=f"{k}_xlsx",
        data=sv.excel_consolidado(filas, incluidas, periodo, dimension, tarifa_sim, ret,
                                  f"Consolidado de horas · {nombre_persona}", desde, hasta, comparacion),
        file_name=f"consolidado_{(codigo or 'equipo')}_{desde:%Y%m%d}_{hasta:%Y%m%d}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ------------------------------------------------------------------ carreras
def _texto(v) -> str:
    """Celda de tabla editable -> texto ('' si está vacía)."""
    return v.strip() if isinstance(v, str) else ""


def _evento_nuevo(conf: dict) -> Evento:
    return Evento(id=None, nombre="", fecha=sv.hoy(), estado="cotizado",
                  reglas=ReglasReparto(base=conf["base_reparto"], pct_empresa=conf["pct_empresa"],
                                       pct_director=conf["pct_director"], pct_equipo=conf["pct_equipo"]))


def _cargar_carrera_ejemplo(conn) -> None:
    pers = list(sv.personas(conn))
    equipo = [{"codigo": pers[0], "rol": DIRECTOR, "peso": 1}] + \
             [{"codigo": c, "rol": TECNICO, "peso": 1} for c in pers[1:3]]
    sv.guardar_evento(conn, None, {
        "nombre": "Ejemplo — Trail 300 corredores", "fecha": sv.hoy(), "estado": REALIZADO,
        "cliente": "Cliente de ejemplo", "venta_neta": 1_800_000, "base_reparto": "margen",
        "pct_empresa": 50, "pct_director": 15, "pct_equipo": 35,
    }, [{"tipo": "Viáticos", "monto": 120_000, "descripcion": "3 personas × 2 días"},
        {"tipo": "Transporte / bencina / peajes", "monto": 180_000},
        {"tipo": "Alojamiento", "monto": 150_000},
        {"tipo": "Chips e insumos", "monto": 210_000, "descripcion": "300 chips sticker"}], equipo)


def bloque_subir_factura(eventos: list, nombres_ev: dict) -> None:
    s = st.session_state
    n = s.get("n_subida", 0)
    archivo = st.file_uploader("Factura en PDF (la que emite TIMER)", type=["pdf"], key=f"factura_pdf_{n}")
    if archivo is None:
        st.caption("Sube el PDF y la app lee el N°, fecha, cliente, neto, IVA y total. Revisa los datos antes de guardar.")
        return
    contenido = archivo.getvalue()
    firma = (archivo.name, len(contenido))
    if s.get("factura_leida", (None,))[0] != firma:
        try:
            s.factura_leida = (firma, sv.leer_pdf_factura(contenido))
        except RuntimeError as e:
            st.error(str(e))
            return
    d = s.factura_leida[1]
    for aviso in d["avisos"]:
        st.warning(aviso)
    kf = f"fac{n}"
    a, b, c = st.columns(3)
    numero = a.text_input("N° factura", value=d["numero"], key=f"{kf}_num")
    fecha = b.date_input("Fecha de emisión", value=d["fecha"], format="DD/MM/YYYY", key=f"{kf}_fecha")
    rut = c.text_input("RUT cliente", value=d["rut_cliente"], key=f"{kf}_rut")
    cliente = st.text_input("Cliente", value=d["cliente"], key=f"{kf}_cli")
    descripcion = st.text_area("Descripción", value=d["descripcion"], key=f"{kf}_desc", height=70)
    a, b, c = st.columns(3)
    neto = a.number_input("Neto", min_value=0, step=1000, value=int(d["neto"]), key=f"{kf}_neto")
    iva = b.number_input("IVA", min_value=0, step=1000, value=int(d["iva"]), key=f"{kf}_iva")
    total = c.number_input("Total", min_value=0, step=1000, value=int(d["total"]), key=f"{kf}_total")
    if neto + iva != total:
        st.warning(f"Neto + IVA = {pesos(neto + iva)}, pero el total dice {pesos(total)}.")

    st.markdown("**¿A qué carrera corresponde?**")
    a, b = st.columns(2)
    destino = a.selectbox("Carrera", [None] + [e.id for e in eventos], key=f"{kf}_destino",
                          format_func=lambda i: "➕ Crear carrera nueva con esta factura" if i is None else nombres_ev[i])
    nombre_nuevo = ""
    if destino is None:
        nombre_nuevo = b.text_input("Nombre de la carrera nueva", value=(d["descripcion"] or "").split(".")[0][:80], key=f"{kf}_nombre")
    a, b = st.columns(2)
    cuota = a.radio("Esta factura es…", ["100", "50", "otro"], horizontal=True, key=f"{kf}_cuota",
                    format_func={"100": "El 100 % (todo)", "50": "El 50 % (anticipo o saldo)", "otro": "Otro %"}.get)
    pct = 100.0 if cuota == "100" else 50.0 if cuota == "50" else \
        b.number_input("% del total de la carrera", min_value=1.0, max_value=100.0, value=30.0, step=5.0, key=f"{kf}_pct")
    ev = next((e for e in eventos if e.id == destino), None)
    if ev is None or not ev.venta_neta:
        st.info(f"Valor total de la carrera (neto): **{pesos(neto * 100 / pct)}** — "
                f"esta factura es el {pct:g} %.")
    else:
        st.info(f"La carrera vale {pesos(ev.venta_neta)} neto: esta factura es el "
                f"**{neto / ev.venta_neta * 100:.0f} %**.")
    a, b = st.columns(2)
    pagada = a.checkbox("El cliente ya la pagó", key=f"{kf}_pagada")
    fecha_pago = b.date_input("Fecha de pago", value=sv.hoy(), format="DD/MM/YYYY", key=f"{kf}_fpago") if pagada else None
    if st.button("Guardar factura", type="primary", key=f"{kf}_guardar"):
        ok, msg, eid = con_bd(sv.guardar_factura, {
            "numero": numero, "fecha": fecha, "cliente": cliente, "rut_cliente": rut, "descripcion": descripcion,
            "neto": neto, "iva": iva, "total": total, "pagada": pagada, "fecha_pago": fecha_pago,
        }, destino, pct, nombre_nuevo, contenido, archivo.name)
        avisar(ok, msg)
        if ok:
            for clave in [x for x in s if str(x).startswith(f"ev{eid}_")]:
                s.pop(clave, None)
            s.n_subida = n + 1
            s.pop("factura_leida", None)
            s["_ir_a_carrera"] = eid
        st.rerun()


def bloque_cobranza(ev) -> None:
    st.markdown("#### Facturación y cobranza")
    cob = con_bd(sv.cobranza, ev)
    m = st.columns(4)
    m[0].metric("Valor carrera (neto)", pesos(cob["contrato"]))
    m[1].metric("Facturado", pesos(cob["facturado"]), f"{cob['pct_facturado']:.0f} %", delta_color="off")
    m[2].metric("Pagado por el cliente", pesos(cob["pagado"]), f"{cob['pct_pagado']:.0f} %", delta_color="off")
    m[3].metric("Por facturar", pesos(cob["por_facturar"]))
    for aviso in cob["avisos"]:
        st.warning(aviso)
    if not cob["facturas"]:
        st.caption("Sin facturas todavía. Regístralas en «📄 Registrar factura (PDF)» (arriba).")
        return
    vista = pd.DataFrame(cob["facturas"])
    for col in ("Neto", "IVA", "Total"):
        vista[col] = vista[col].map(pesos)
    vista["% de la carrera"] = vista["% de la carrera"].map(lambda x: f"{x:g} %")
    vista["Pagada"] = vista["Pagada"].map(lambda x: "Sí" if x else "No")
    vista["PDF"] = vista["PDF"].map(lambda x: "📄" if x else "")
    st.dataframe(vista.drop(columns=["id"]), hide_index=True, width="stretch")
    por_id = {f["id"]: f for f in cob["facturas"]}
    a, b, c, d = st.columns([2, 1, 1, 1])
    fid = a.selectbox("Factura", list(por_id), key=f"ev{ev.id}_fac_sel",
                      format_func=lambda i: f"N° {por_id[i]['N°'] or '—'} · {pesos(por_id[i]['Neto'])} neto")
    f = por_id[fid]
    if f["Pagada"]:
        if b.button("Marcar no pagada", key=f"ev{ev.id}_nopag"):
            avisar(*con_bd(sv.marcar_pago_factura, fid, False, None))
            st.rerun()
    elif b.button("✅ Marcar pagada hoy", key=f"ev{ev.id}_pag"):
        avisar(*con_bd(sv.marcar_pago_factura, fid, True, sv.hoy()))
        st.rerun()
    if f["PDF"]:
        archivo = con_bd(sv.archivo_factura, fid)
        if archivo:
            c.download_button("Descargar PDF", data=archivo[0], file_name=archivo[1], mime="application/pdf",
                              key=f"ev{ev.id}_pdf_{fid}")
    if d.button("Quitar factura", key=f"ev{ev.id}_quitar"):
        avisar(*con_bd(sv.anular_factura, fid))
        st.rerun()


ICONO_BOLETA = {"pendiente": "⚪", "solicitada": "✉️", "recibida": "📄", "pagada": "✅"}


def bloque_pagos_equipo(ev) -> None:
    st.markdown("#### Honorarios del equipo y boletas")
    pagos = con_bd(sv.pagos_de_carrera, ev)
    if not pagos:
        st.caption("No hay pagos: revisa que la carrera tenga equipo y margen.")
        return
    st.dataframe(pd.DataFrame([{
        "Persona": p["nombre"], "Rol": p["roles"], "Jornadas": p["jornadas"], "Bruto a boletear": pesos(p["bruto"]),
        "Retención": pesos(p["retencion"]), "Líquido a pagar": pesos(p["liquido"]),
        "Boleta": f"{ICONO_BOLETA[p['estado']]} {sv.ESTADOS_BOLETA[p['estado']]}"
                  + (f" N° {p['numero_boleta']}" if p["numero_boleta"] else ""),
    } for p in pagos]), hide_index=True, width="stretch")
    st.caption("Se envía un correo a cada persona con su monto. Se abre en tu programa de correo para que lo revises "
               "y lo envíes tú.")
    for p in pagos:
        with st.expander(f"{ICONO_BOLETA[p['estado']]} {p['nombre']} — {pesos(p['bruto'])} bruto"):
            asunto, cuerpo = con_bd(sv.mensaje_boleta, ev, p)
            st.text_input("Asunto", value=asunto, key=f"ev{ev.id}_asunto_{p['codigo']}", disabled=True)
            st.code(cuerpo, language=None, wrap_lines=True)
            a, b, c, d = st.columns(4)
            if p["email"]:
                a.link_button("✉️ Abrir correo", sv.enlace_correo(p["email"], asunto, cuerpo))
            else:
                a.warning("Falta su correo (Personas).")
            if b.button("Marcar solicitada", key=f"ev{ev.id}_sol_{p['codigo']}", disabled=p["estado"] != "pendiente"):
                avisar(*con_bd(sv.cambiar_estado_boleta, ev, p["codigo"], "solicitada"))
                st.rerun()
            numero = c.text_input("N° boleta", value=p["numero_boleta"], key=f"ev{ev.id}_num_{p['codigo']}",
                                  label_visibility="collapsed", placeholder="N° boleta")
            if c.button("Marcar recibida", key=f"ev{ev.id}_rec_{p['codigo']}", disabled=p["estado"] == "pagada"):
                avisar(*con_bd(sv.cambiar_estado_boleta, ev, p["codigo"], "recibida", numero.strip()))
                st.rerun()
            if d.button("✅ Marcar pagada", key=f"ev{ev.id}_pag_{p['codigo']}", disabled=p["estado"] == "pagada"):
                avisar(*con_bd(sv.cambiar_estado_boleta, ev, p["codigo"], "pagada", numero.strip()))
                st.rerun()
            if p["tiene_pdf"]:
                archivo = con_bd(sv.archivo_boleta, ev.id, p["codigo"])
                if archivo:
                    st.download_button("Descargar boleta (PDF)", data=archivo[0], file_name=archivo[1],
                                       mime="application/pdf", key=f"ev{ev.id}_bpdf_{p['codigo']}")


def pestana_mis_pagos(codigo: str) -> None:
    pagos = con_bd(sv.mis_pagos, codigo)
    if not pagos:
        st.info("Todavía no tienes pagos de carreras. Aparecen aquí cuando una carrera en la que participaste "
                "queda como «Realizado».")
        return
    por_pagar = [p for p in pagos if p["estado"] != "pagada" and p["aprobado"]]
    m = st.columns(3)
    m[0].metric("Carreras", len(pagos))
    m[1].metric("Líquido por recibir", pesos(sum(p["liquido"] for p in por_pagar)))
    m[2].metric("Boletas pendientes", sum(1 for p in pagos if p["aprobado"] and p["estado"] in ("pendiente", "solicitada")))
    st.dataframe(pd.DataFrame([{
        "Fecha": p["evento"].fecha.strftime("%d-%m-%Y") if p["evento"].fecha else "", "Carrera": p["evento"].nombre,
        "Rol": p["roles"], "Bruto": pesos(p["bruto"]), "Retención": pesos(p["retencion"]),
        "Líquido": pesos(p["liquido"]),
        "Estado": f"{ICONO_BOLETA[p['estado']]} {sv.ESTADOS_BOLETA[p['estado']]}" if p["aprobado"] else "⏳ En aprobación",
    } for p in pagos]), hide_index=True, width="stretch")
    for p in por_pagar:
        ev = p["evento"]
        with st.expander(f"{ev.nombre}: emitir y subir mi boleta"):
            asunto, cuerpo = con_bd(sv.mensaje_boleta, ev, p)
            st.code(cuerpo, language=None, wrap_lines=True)
            with st.form(f"mi_boleta_{ev.id}", clear_on_submit=True):
                numero = st.text_input("N° de tu boleta", value=p["numero_boleta"])
                archivo = st.file_uploader("PDF de la boleta", type=["pdf"])
                if st.form_submit_button("Subir boleta", type="primary"):
                    avisar(*con_bd(sv.cambiar_estado_boleta, ev, codigo, "recibida", numero.strip(),
                                   archivo.getvalue() if archivo else None, archivo.name if archivo else None,
                                   codigo))
                    st.rerun()


def pestana_carreras() -> None:
    conf = con_bd(sv.configuracion)
    eventos = con_bd(sv.eventos)
    pers = con_bd(sv.personas)
    prods = con_bd(sv.productos)

    if eventos:
        resumen = []
        for e in eventos:
            r = con_bd(sv.resumen_evento, e)["reparto"]
            cob = con_bd(sv.cobranza, e)
            resumen.append({"Fecha": e.fecha.strftime("%d-%m-%Y") if e.fecha else "", "Carrera": e.nombre,
                            "Estado": NOMBRE_ESTADO_EVENTO[e.estado],
                            "Total c/IVA": pesos(desglose(r.venta_neta, e.tasa_iva, False)["total"]),
                            "Venta neta": pesos(r.venta_neta),
                            "Gastos": pesos(r.total_gastos), "Margen": pesos(r.margen),
                            "Margen %": f"{r.margen_pct:.0f} %",
                            "Personal": pesos(r.monto_director + r.monto_equipo), "Empresa": pesos(r.monto_empresa),
                            "Facturado": f"{cob['pct_facturado']:.0f} %", "Pagado": f"{cob['pct_pagado']:.0f} %"})
        st.dataframe(pd.DataFrame(resumen), hide_index=True, width="stretch")
    elif MODO_LOCAL:
        if st.button("Cargar una carrera de ejemplo"):
            con_bd(_cargar_carrera_ejemplo)
            st.rerun()

    nombres_ev = {e.id: f"{e.nombre} ({e.fecha:%d-%m-%Y})" if e.fecha else e.nombre for e in eventos}
    with st.expander("📄 Registrar factura (PDF)", expanded=not eventos):
        bloque_subir_factura(eventos, nombres_ev)

    opciones = [None] + [e.id for e in eventos]
    if "_ir_a_carrera" in st.session_state:
        st.session_state.carrera_elegida = st.session_state.pop("_ir_a_carrera")
    eid = st.selectbox("Carrera", opciones, format_func=lambda i: "➕ Nueva carrera / simular cotización"
                       if i is None else nombres_ev[i], key="carrera_elegida")
    ev = next((e for e in eventos if e.id == eid), None) or _evento_nuevo(conf)
    extra = con_bd(sv.datos_extra_evento, eid) if eid else {"hubspot_deal": "", "notas": ""}
    k = f"ev{eid or 'nuevo'}"

    st.markdown("#### Datos de la carrera")
    a, b, c = st.columns([3, 1, 1])
    nombre = a.text_input("Nombre", value=ev.nombre, key=f"{k}_nombre")
    fecha = b.date_input("Fecha", value=ev.fecha, format="DD/MM/YYYY", key=f"{k}_fecha")
    estado = c.selectbox("Estado", ESTADOS_EVENTO, index=ESTADOS_EVENTO.index(ev.estado),
                         format_func=NOMBRE_ESTADO_EVENTO.get, key=f"{k}_estado")
    a, b, c = st.columns(3)
    cliente = a.text_input("Cliente", value=ev.cliente, key=f"{k}_cliente")
    lista_prod = [None] + list(prods)
    producto = b.selectbox("Línea de producto", lista_prod,
                           index=lista_prod.index(ev.producto_id) if ev.producto_id in lista_prod else 0,
                           format_func=lambda i: "—" if i is None else prods[i], key=f"{k}_prod")
    hubspot = c.text_input("Negocio en HubSpot (enlace o ID)", value=extra["hubspot_deal"], key=f"{k}_hs")

    st.markdown("#### Facturación e IVA")
    a, b, c = st.columns(3)
    tasas = [IVA_CHILE, 0.0]
    tasa_iva = a.selectbox("Documento al cliente", tasas, index=0 if ev.tasa_iva else 1, key=f"{k}_doc",
                           format_func=lambda t: f"Factura afecta (IVA {t:g} %)" if t else "Factura exenta (sin IVA)")
    modo = b.radio("El monto que escribes es…", ["total", "neto"], horizontal=True, key=f"{k}_modo",
                   format_func=lambda m: "Total transferido (con IVA)" if m == "total" else "Neto (sin IVA)",
                   help="Lo más fácil: el monto que el cliente transfirió a TIMER, o el total de la factura.")
    inicial = desglose(ev.venta_neta, ev.tasa_iva, incluye_iva=False)
    otro = "neto" if modo == "total" else "total"
    if f"{k}_monto_{otro}" in st.session_state:  # si cambió el modo, convierte lo que ya había escrito
        inicial = desglose(st.session_state[f"{k}_monto_{otro}"], tasa_iva, incluye_iva=(otro == "total"))
    monto = c.number_input("Monto (CLP)", min_value=0, step=10_000,
                           value=int(inicial["total"] if modo == "total" else inicial["neto"]), key=f"{k}_monto_{modo}")
    partes = desglose(monto, tasa_iva, incluye_iva=(modo == "total"))
    venta = partes["neto"]
    a, b, c = st.columns(3)
    a.metric("Total facturado / transferido", pesos(partes["total"]))
    b.metric("IVA (se paga al SII)", pesos(partes["iva"]), help="No es ingreso de TIMER: se declara y paga al SII "
             "en el F29, descontando el IVA de las compras con factura.")
    c.metric("Neto para TIMER", pesos(partes["neto"]), help="Sobre este valor se calculan margen y reparto.")

    st.markdown("#### Gastos operacionales (viáticos, traslados, alojamiento…)")
    gastos_df = pd.DataFrame([{"Tipo": g.tipo, "Detalle": g.descripcion, "Monto": int(g.monto)} for g in ev.gastos]
                             or [{"Tipo": "Viáticos", "Detalle": "", "Monto": 0}])
    gastos_ed = st.data_editor(gastos_df, num_rows="dynamic", width="stretch", key=f"{k}_gastos",
                               column_config={
                                   "Tipo": st.column_config.SelectboxColumn(options=TIPOS_GASTO, required=True),
                                   "Monto": st.column_config.NumberColumn("Monto (CLP)", min_value=0, step=1000),
                               })

    st.markdown("#### Equipo de trabajo y distribución de honorarios")
    a, b = st.columns([2, 3], gap="large")
    bases = list(BASES_REPARTO)
    base = a.radio("Los porcentajes se calculan sobre", bases, index=bases.index(ev.reglas.base),
                   format_func=BASES_REPARTO.get, key=f"{k}_base")
    p1, p2, p3 = b.columns(3)
    pct_emp = p1.number_input("Empresa %", 0.0, 100.0, float(ev.reglas.pct_empresa), 1.0, key=f"{k}_pe")
    pct_dir = p2.number_input("Director de carrera %", 0.0, 100.0, float(ev.reglas.pct_director), 1.0, key=f"{k}_pd")
    pct_eq = p3.number_input("Equipo TIMER %", 0.0, 100.0, float(ev.reglas.pct_equipo), 1.0, key=f"{k}_pq")

    conf_niv = con_bd(sv.configuracion)
    niveles = con_bd(sv.niveles_de_funciones)
    funciones_act = [f["nombre"] for f in con_bd(sv.lista_funciones, True)]
    for i in ev.equipo:   # funciones antiguas o desactivadas siguen visibles en su carrera
        if i.funcion and i.funcion not in funciones_act:
            funciones_act.append(i.funcion)
    ponderar = st.toggle("Ponderar por función (meta, partida, apoyo…)", key=f"{k}_ponderar",
                         value=any(i.funcion or i.factor_manual is not None for i in ev.equipo),
                         help="Activado: la parte del equipo se reparte según jornadas × ponderación de la función. "
                              "Desactivado: todos valen lo mismo por jornada.")
    etiquetas_p = {f"{p.nombre} ({c})": c for c, p in pers.items() if p.activo}
    inverso = {v: kk for kk, v in etiquetas_p.items()}
    roles_inv = {v: kk for kk, v in ROLES.items()}
    equipo_df = pd.DataFrame([{"Persona": inverso.get(i.codigo, i.codigo), "Rol": ROLES[i.rol],
                               "Función": i.funcion or None, "Jornadas": i.peso, "Ponderación": i.factor_manual}
                              for i in ev.equipo]
                             or [{"Persona": None, "Rol": ROLES[DIRECTOR], "Función": None, "Jornadas": 1.0,
                                  "Ponderación": None}])
    equipo_df["Ponderación"] = pd.to_numeric(equipo_df["Ponderación"], errors="coerce")
    columnas = ["Persona", "Rol", "Función", "Jornadas", "Ponderación"] if ponderar else ["Persona", "Rol", "Jornadas"]
    equipo_ed = st.data_editor(equipo_df, num_rows="dynamic", width="stretch", key=f"{k}_equipo",
                               column_order=columnas,
                               column_config={
                                   "Persona": st.column_config.SelectboxColumn(options=list(etiquetas_p)),
                                   "Rol": st.column_config.SelectboxColumn(options=list(ROLES.values()), required=True),
                                   "Función": st.column_config.SelectboxColumn(options=funciones_act, width="large",
                                       help="Define el nivel (1, 2 o 3) y con eso su ponderación."),
                                   "Jornadas": st.column_config.NumberColumn(min_value=0.0, step=0.5,
                                       help="Días o jornadas trabajadas en la carrera."),
                                   "Ponderación": st.column_config.NumberColumn(
                                       "Ponderación (opcional)", min_value=0.0, max_value=10.0, step=0.1, format="%.2f",
                                       help="Déjala vacía para usar la del nivel de la función. Escríbela para un caso especial."),
                               })
    if ponderar:
        st.caption(f"Ponderación por nivel: Nivel 1 = ×{conf_niv['factor_nivel1']:g} · Nivel 2 = ×{conf_niv['factor_nivel2']:g}"
                   f" · Nivel 3 = ×{conf_niv['factor_nivel3']:g} · sin función = ×1. Se cambian en Configuración.")
    notas = st.text_area("Notas", value=extra["notas"], key=f"{k}_notas", height=70)

    # ---- armar la carrera con lo que está en pantalla y calcular en vivo
    gastos = [{"tipo": _texto(r.get("Tipo")) or "Otros", "descripcion": _texto(r.get("Detalle")),
               "monto": float(r["Monto"])}
              for r in gastos_ed.to_dict("records") if pd.notna(r.get("Monto"))]
    equipo = [{"codigo": etiquetas_p.get(r["Persona"], r["Persona"]),
               "rol": roles_inv.get(_texto(r.get("Rol")), TECNICO),
               "peso": float(r["Jornadas"]) if pd.notna(r.get("Jornadas")) else 1.0,
               "funcion": _texto(r.get("Función")) if ponderar else "",
               "factor": float(r["Ponderación"]) if ponderar and pd.notna(r.get("Ponderación")) else None}
              for r in equipo_ed.to_dict("records") if _texto(r.get("Persona"))]
    vivo = Evento(id=eid, nombre=nombre, fecha=fecha, venta_neta=venta, estado=estado, tasa_iva=tasa_iva,
                  reglas=ReglasReparto(base=base, pct_empresa=pct_emp, pct_director=pct_dir, pct_equipo=pct_eq),
                  gastos=[Gasto(g["tipo"], g["monto"]) for g in gastos],
                  equipo=[Integrante(i["codigo"], i["rol"], i["peso"], funcion=i["funcion"], factor_manual=i["factor"],
                                     factor=sv.factor_de(conf_niv, niveles, i["funcion"], i["factor"]))
                          for i in equipo])
    info = con_bd(sv.resumen_evento, vivo)
    r = info["reparto"]

    st.markdown("#### Resultado económico")
    m = st.columns(6)
    m[0].metric("Venta neta", pesos(r.venta_neta))
    m[1].metric("Gastos operacionales", pesos(r.total_gastos))
    m[2].metric("Margen", pesos(r.margen), f"{r.margen_pct:.0f} % de la venta", delta_color="off")
    m[3].metric("Honorarios director", pesos(r.monto_director))
    m[4].metric("Honorarios equipo", pesos(r.monto_equipo))
    m[5].metric("Resultado empresa", pesos(r.monto_empresa))
    for alerta in r.alertas:
        st.warning(alerta)
    if r.pagos:
        filas_pago = []
        for p in r.pagos:
            fila_p = {"Persona": info["nombres"].get(p.codigo, p.codigo), "Rol": ROLES[p.rol]}
            if ponderar:
                nivel = niveles.get(p.funcion)
                fila_p.update({"Función": p.funcion or "—", "Nivel": nivel or "—", "Jornadas": p.peso,
                               "Ponderación": f"×{p.factor:g}"})
            else:
                fila_p["Jornadas"] = p.peso
            fila_p.update({"Participación": f"{p.participacion:.1f} %", "Honorario bruto": pesos(p.monto)})
            filas_pago.append(fila_p)
        st.dataframe(pd.DataFrame(filas_pago), hide_index=True, width="stretch")
        st.caption("Participación = % dentro de su grupo (director o equipo). El honorario bruto es el monto a boletear.")
    if info["horas_internas"]:
        st.info(f"Además se cargaron **{horas_texto(info['horas_internas'])}** de preparación a esta carrera "
                f"(valor {pesos(info['costo_horas_internas'])} pagado por hora). "
                f"Lo que realmente le queda a la empresa: **{pesos(info['resultado_final_empresa'])}**.")
    if estado not in ("realizado", "pagado"):
        st.caption("Mientras no esté «Realizado» o «Pagado», esto es solo una estimación: no entra al sueldo del mes.")

    if eid is not None:
        bloque_cobranza(ev)
        if ev.estado in ("realizado", "pagado") and ev.honorarios_aprobados:
            st.success("✅ Honorarios aprobados: ya entran a la liquidación mensual.")
            bloque_pagos_equipo(ev)
            if st.button("Quitar aprobación de honorarios", key=f"{k}_desaprobar"):
                avisar(*con_bd(sv.aprobar_honorarios_carrera, eid, st.session_state.admin, False))
                st.rerun()
        elif ev.estado in ("realizado", "pagado"):
            st.info("⏳ Los honorarios de esta carrera están **por aprobar**. Revisa el reparto y apruébalo aquí o en "
                    "«Aprobaciones». Después aparece el correo para pedir las boletas.")
            if st.button("✅ Aprobar honorarios", type="primary", key=f"{k}_aprobar"):
                avisar(*con_bd(sv.aprobar_honorarios_carrera, eid, st.session_state.admin))
                st.rerun()
        else:
            st.caption("Cuando la carrera esté «Realizado» y guardada, aquí aparecerán los pagos del equipo "
                       "y el correo para pedir las boletas de honorarios.")

    g1, g2 = st.columns([1, 4])
    if eid is not None:
        with g2.popover("🗑️ Borrar carrera"):
            st.warning(f"Se borrará «{ev.nombre}» con sus gastos, equipo y facturas. "
                       "Las horas cargadas a ella se mantienen, pero quedan sin carrera. No se puede deshacer.")
            if st.button("Sí, borrar definitivamente", type="primary", key=f"{k}_borrar"):
                ok, msg = con_bd(sv.eliminar_evento, eid)
                avisar(ok, msg)
                if ok:
                    for clave in [x for x in st.session_state if str(x).startswith(f"{k}_")]:
                        st.session_state.pop(clave, None)
                    st.session_state["_ir_a_carrera"] = None
                st.rerun()
    if g1.button("Guardar carrera", type="primary", key=f"{k}_guardar"):
        ok, msg, nuevo_id = con_bd(sv.guardar_evento, eid, {
            "nombre": nombre, "fecha": fecha, "cliente": cliente, "producto_id": producto, "estado": estado,
            "venta_neta": venta, "tasa_iva": tasa_iva, "base_reparto": base, "pct_empresa": pct_emp, "pct_director": pct_dir,
            "pct_equipo": pct_eq, "hubspot_deal": hubspot, "notas": notas,
        }, gastos, equipo)
        avisar(ok, msg)
        if ok:
            for clave in [x for x in st.session_state if str(x).startswith("evnuevo_")]:
                st.session_state.pop(clave, None)
            st.session_state["_ir_a_carrera"] = nuevo_id
        st.rerun()


# ------------------------------------------------------------------ personas
def pestana_personas() -> None:
    filas = con_bd(sv.lista_personas)
    if filas:
        st.dataframe(pd.DataFrame([{
            "Código": f["codigo"], "Nombre": f["nombre"], "Cargo": f["cargo"],
            "Tarifa/hora": pesos(float(f["tarifa_hora"])), "Activo": "Sí" if f["activo"] else "No",
            "PIN": "Sí" if f["tiene_pin"] else "Falta", "Correo": f.get("email") or "—",
        } for f in filas]), hide_index=True, width="stretch")
    nombres = {f["codigo"]: f"{f['nombre']} ({f['codigo']})" for f in filas}
    activos = [f["codigo"] for f in filas if f["activo"]]
    c1, c2 = st.columns(2, gap="large")
    with c1:
        if activos:
            st.subheader("Asignar o cambiar PIN")
            with st.form("form_pin", clear_on_submit=True):
                cod = st.selectbox("Persona", activos, format_func=nombres.get)
                p1 = st.text_input("PIN nuevo (4 números)", type="password", max_chars=4)
                p2 = st.text_input("Repite el PIN", type="password", max_chars=4)
                if st.form_submit_button("Guardar PIN"):
                    avisar(*con_bd(sv.asignar_pin, cod, p1.strip(), p2.strip()))
                    st.rerun()
        st.subheader("Agregar persona")
        with st.form("form_nueva", clear_on_submit=True):
            codigo = st.text_input("Código", value=con_bd(sv.siguiente_codigo))
            nombre = st.text_input("Nombre y apellido")
            cargo = st.text_input("Cargo (ej. Técnico, Comercial)")
            tarifa = st.number_input("Tarifa por hora (CLP)", min_value=0, step=500, value=6000)
            email = st.text_input("Correo (para pedirle boletas)")
            if st.form_submit_button("Agregar"):
                ok, msg = con_bd(sv.guardar_persona, {"codigo": codigo, "nombre": nombre, "cargo": cargo,
                                                      "tarifa_hora": tarifa}, True)
                if ok and email.strip():
                    ok2, msg2 = con_bd(sv.guardar_contacto, codigo.strip().lower(), email, "")
                    msg = msg if ok2 else f"{msg} {msg2}"
                avisar(ok, msg)
                st.rerun()
    with c2:
        if filas:
            st.subheader("Editar persona")
            sel = st.selectbox("Persona a editar", [f["codigo"] for f in filas], format_func=nombres.get,
                               key="persona_a_editar")
            f = next(x for x in filas if x["codigo"] == sel)
            with st.form(f"form_editar_{sel}"):
                nombre = st.text_input("Nombre", value=f["nombre"])
                cargo = st.text_input("Cargo", value=f["cargo"])
                tarifa = st.number_input("Tarifa por hora (CLP)", min_value=0, step=500, value=int(float(f["tarifa_hora"])))
                email = st.text_input("Correo", value=f.get("email") or "")
                telefono = st.text_input("Teléfono", value=f.get("telefono") or "")
                activo = st.checkbox("Activo (puede registrar horas)", value=bool(f["activo"]))
                if st.form_submit_button("Guardar cambios"):
                    ok, msg = con_bd(sv.guardar_persona, {"codigo": sel, "nombre": nombre, "cargo": cargo,
                                                          "tarifa_hora": tarifa, "activo": activo}, False)
                    if ok:
                        ok, msg2 = con_bd(sv.guardar_contacto, sel, email, telefono)
                        msg = msg if ok else msg2
                    avisar(ok, msg)
                    st.rerun()
    if activos:
        st.divider()
        st.subheader("Cargar horas por otra persona")
        st.caption("Para cuando alguien te pasa sus horas por WhatsApp.")
        if st.toggle("Mostrar", key="cargar_por_otro"):
            quien = st.selectbox("¿De quién?", activos, format_func=nombres.get, key="quien_cargo")
            if st.radio("Forma", ["dia", "rapida"], horizontal=True, key="forma_carga",
                        format_func={"dia": "Un día (carrito)", "rapida": "Varios días (tabla / Excel)"}.get) == "dia":
                pestana_registrar(quien, creado_por=st.session_state.admin)
            else:
                pestana_carga_rapida(quien, creado_por=st.session_state.admin)


# ------------------------------------------------------------------ ajustes
def pestana_ajustes() -> None:
    conf = con_bd(sv.configuracion)
    if MODO_LOCAL:
        with st.expander("🧹 Empezar de cero (modo prueba)"):
            st.write("Borra **todas** las horas, carreras y facturas. Mantiene personas, PIN, tarifas, "
                     "categorías y estos ajustes.")
            confirmar = st.text_input("Para confirmar escribe BORRAR", key="confirmar_borrado")
            if st.button("Borrar datos", disabled=confirmar.strip().upper() != "BORRAR"):
                avisar(*con_bd(sv.borrar_datos_de_prueba))
                st.session_state.pop("confirmar_borrado", None)
                st.session_state["_ir_a_carrera"] = None
                st.rerun()
    st.subheader("Parámetros generales")
    with st.form("form_config"):
        a, b = st.columns(2)
        empresa = a.text_input("Nombre de la empresa", value=conf["nombre_empresa"])
        ret = b.number_input("Retención boleta de honorarios (%)", 0.0, 100.0, conf["pct_retencion"], 0.25)
        bases = list(BASES_REPARTO)
        base = st.radio("Reparto de carreras sobre", bases, index=bases.index(conf["base_reparto"]),
                        format_func=BASES_REPARTO.get, horizontal=True)
        a, b, c = st.columns(3)
        pe = a.number_input("Empresa %", 0.0, 100.0, conf["pct_empresa"], 1.0)
        pd_ = b.number_input("Director de carrera %", 0.0, 100.0, conf["pct_director"], 1.0)
        pq = c.number_input("Equipo TIMER %", 0.0, 100.0, conf["pct_equipo"], 1.0)
        st.markdown("**Datos para las boletas de honorarios** (van en el correo a cada persona)")
        a, b = st.columns(2)
        razon = a.text_input("Razón social (receptor de la boleta)", value=conf["razon_social"])
        rut = b.text_input("RUT", value=conf["rut_empresa"])
        a, b, c = st.columns([2, 2, 1])
        direccion = a.text_input("Dirección", value=conf["direccion_empresa"])
        correo = b.text_input("Correo de finanzas", value=conf["email_finanzas"])
        dias = c.number_input("Días para pagar", min_value=1, max_value=60, value=conf["dias_pago"])
        if st.form_submit_button("Guardar"):
            avisar(*con_bd(sv.guardar_configuracion, {"nombre_empresa": empresa.strip() or "TIMER",
                                                      "pct_retencion": ret, "base_reparto": base,
                                                      "pct_empresa": pe, "pct_director": pd_, "pct_equipo": pq,
                                                      "razon_social": razon.strip(), "rut_empresa": rut.strip(),
                                                      "direccion_empresa": direccion.strip(),
                                                      "email_finanzas": correo.strip(), "dias_pago": int(dias)}))
            st.rerun()

    st.subheader("Funciones en carrera y ponderación")
    st.caption("Cada función pertenece a un nivel (1, 2 o 3 = los tres rangos de pago). La parte del equipo se "
               "reparte según jornadas × ponderación. Ejemplo: Meta (nivel 1, ×1,5) recibe 1,5 veces lo de "
               "Partida (nivel 2, ×1) por la misma jornada.")
    from basedatos.datos_iniciales import NIVELES
    a, b, c = st.columns(3)
    f1 = a.number_input(NIVELES[1], 0.1, 10.0, conf["factor_nivel1"], 0.1, key="factor_n1")
    f2 = b.number_input(NIVELES[2], 0.1, 10.0, conf["factor_nivel2"], 0.1, key="factor_n2")
    f3 = c.number_input(NIVELES[3], 0.1, 10.0, conf["factor_nivel3"], 0.1, key="factor_n3")
    funcs = con_bd(sv.lista_funciones)
    funcs_df = pd.DataFrame([{"Función": f["nombre"], "Nivel": int(f["nivel"]), "Activa": bool(f["activo"])}
                             for f in funcs] or [{"Función": "", "Nivel": 2, "Activa": True}])
    funcs_ed = st.data_editor(funcs_df, num_rows="dynamic", width="stretch", key="tabla_funciones",
                              column_config={
                                  "Función": st.column_config.TextColumn(width="large", required=True),
                                  "Nivel": st.column_config.SelectboxColumn(options=[1, 2, 3], required=True,
                                                                            help="1 = mayor responsabilidad"),
                                  "Activa": st.column_config.CheckboxColumn(),
                              })
    if st.button("Guardar funciones y ponderaciones", type="primary"):
        lista = [{"nombre": _texto(r.get("Función")), "nivel": int(r["Nivel"]) if pd.notna(r.get("Nivel")) else 2,
                  "activo": bool(r.get("Activa")) if pd.notna(r.get("Activa")) else True}
                 for r in funcs_ed.to_dict("records")]
        avisar(*con_bd(sv.guardar_funciones, lista, {"factor_nivel1": f1, "factor_nivel2": f2, "factor_nivel3": f3}))
        st.session_state.pop("tabla_funciones", None)
        st.rerun()

    st.subheader("Categorías de actividad")
    cats = con_bd(sv.lista_categorias)
    st.dataframe(pd.DataFrame([{
        "Grupo": c["grupo"], "Categoría": c["nombre"],
        "Se paga": "Por hora" if c["pagable_por_hora"] else "Por reparto de carrera",
        "Tarifa especial": pesos(float(c["tarifa_hora_especial"])) if c["tarifa_hora_especial"] else "—",
        "Activa": "Sí" if c["activo"] else "No"} for c in cats]), hide_index=True, width="stretch")
    c1, c2 = st.columns(2, gap="large")
    with c1:
        opciones = [None] + [int(c["id"]) for c in cats]
        por_id = {int(c["id"]): c for c in cats}
        sel = st.selectbox("Editar o crear categoría", opciones,
                           format_func=lambda i: "➕ Nueva categoría" if i is None else por_id[i]["nombre"])
        c = por_id.get(sel, {"nombre": "", "grupo": "", "pagable_por_hora": True, "tarifa_hora_especial": None,
                             "activo": True})
        with st.form(f"form_cat_{sel}"):
            nombre = st.text_input("Nombre", value=c["nombre"])
            grupo = st.text_input("Grupo (Comercial, Taller, Logística, Carrera…)", value=c["grupo"])
            pagable = st.checkbox("Se paga por hora", value=bool(c["pagable_por_hora"]),
                                  help="Desmárcalo si ese trabajo ya se paga con el reparto de la carrera "
                                       "(ej. cronometrar el día de la carrera). Así no se paga dos veces.")
            especial = st.number_input("Tarifa especial por hora (CLP, 0 = usa la de la persona)", min_value=0,
                                       step=500, value=int(float(c["tarifa_hora_especial"] or 0)))
            activa = st.checkbox("Activa", value=bool(c["activo"]))
            if st.form_submit_button("Guardar categoría"):
                avisar(*con_bd(sv.guardar_categoria, {"nombre": nombre, "grupo": grupo, "pagable_por_hora": pagable,
                                                      "tarifa_hora_especial": especial, "activo": activa}, sel))
                st.rerun()
    with c2:
        prods = con_bd(sv.lista_productos)
        por_id_p = {int(p["id"]): p for p in prods}
        selp = st.selectbox("Editar o crear línea de producto", [None] + list(por_id_p),
                            format_func=lambda i: "➕ Nuevo producto" if i is None else por_id_p[i]["nombre"])
        p = por_id_p.get(selp, {"nombre": "", "activo": True})
        with st.form(f"form_prod_{selp}"):
            nombre_p = st.text_input("Nombre", value=p["nombre"])
            activo_p = st.checkbox("Activo", value=bool(p["activo"]))
            if st.form_submit_button("Guardar producto"):
                avisar(*con_bd(sv.guardar_producto, nombre_p, selp, activo_p))
                st.rerun()
        st.caption("Productos actuales: " + ", ".join(p["nombre"] for p in prods if p["activo"]))


def pagina_admin() -> None:
    encabezado("Administración", logo="logo_tmr.png")
    if not st.session_state.get("admin"):
        login_admin()
        return
    c1, c2 = st.columns([5, 1])
    c1.caption(f"Conectado como {st.session_state.admin_nombre}")
    if c2.button("Salir", key="salir_admin"):
        st.session_state.pop("admin", None)
        cambiar_modo(None)
    aviso_pendiente()
    pendientes = len(con_bd(sv.tabla_por_revisar)) + len(con_bd(sv.carreras_por_aprobar))
    t = st.tabs([f"Aprobaciones ({pendientes})", "Liquidación mensual", "Registro de horas", "Resumen por período",
                 "Consolidados y simulador", "Carreras y Honorarios", "Personal", "Configuración"])
    with t[0]:
        pestana_aprobaciones()
    with t[1]:
        pestana_sueldos()
    with t[2]:
        pestana_analisis()
    with t[3]:
        pers = con_bd(sv.personas)
        quien = st.selectbox("Persona", [None] + list(pers), key="resumen_admin_persona",
                             format_func=lambda c: "Todo el equipo" if c is None else pers[c].nombre)
        pestana_resumen(quien, clave="resumen_admin")
    with t[4]:
        pers = con_bd(sv.personas)
        quien = st.selectbox("Persona", [None] + list(pers), key="cons_admin_persona",
                             format_func=lambda c: "Todo el equipo" if c is None else pers[c].nombre)
        pestana_consolidados(quien, clave="cons_admin", autor=st.session_state.get("admin_nombre", "admin"))
    with t[5]:
        pestana_carreras()
    with t[6]:
        pestana_personas()
    with t[7]:
        pestana_ajustes()


# ================================================================== inicio
def main() -> None:
    try:
        motor_bd()
    except Exception as e:  # contraseña mala, sin internet, Supabase pausado...
        st.markdown(ESTILO, unsafe_allow_html=True)
        st.error("No se pudo conectar con la base de datos.")
        st.caption("Revisa el archivo .streamlit/secrets.toml (o los Secrets en Streamlit Cloud) y que el "
                   f"proyecto de Supabase no esté pausado. Detalle técnico: {type(e).__name__}")
        st.stop()
    if st.query_params.get("modo") == "admin":
        pagina_admin()
    else:
        pagina_equipo()


main()
