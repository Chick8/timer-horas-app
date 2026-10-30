"""Todas las consultas a la base de datos.

Funcionan igual en Supabase (PostgreSQL) y en el modo prueba local (SQLite):
por eso las fechas se pasan como texto 'AAAA-MM-DD' y las horas de sistema como texto ISO.

Cada función recibe una conexión abierta (`conn`). Quien la llama decide la
transacción: `with motor_bd.begin() as conn:` guarda todo junto o nada.
"""
from __future__ import annotations

try:
    from sqlalchemy import text as _sql
except ImportError:  # las pruebas sin SQLAlchemy usan una conexión de prueba que acepta texto
    def _sql(consulta):
        return consulta


def _filas(conn, consulta: str, **parametros) -> list[dict]:
    return [dict(f) for f in conn.execute(_sql(consulta), parametros).mappings().all()]


def _fila(conn, consulta: str, **parametros) -> dict | None:
    f = conn.execute(_sql(consulta), parametros).mappings().first()
    return dict(f) if f is not None else None


def _ejecutar(conn, consulta: str, **parametros) -> None:
    conn.execute(_sql(consulta), parametros)


def contar(conn, tabla: str) -> int:
    assert tabla in {"configuracion", "personas", "categorias", "productos", "eventos", "actividades", "funciones"}
    return int(_fila(conn, f"select count(*) as n from {tabla}")["n"])


# ------------------------------------------------------------------ actualizaciones de estructura
COLUMNAS_NUEVAS = [   # (tabla, columna, tipo) — funcionan igual en PostgreSQL y SQLite
    ("eventos", "tasa_iva", "real not null default 19"),
    ("personas", "email", "text not null default ''"),
    ("personas", "telefono", "text not null default ''"),
    ("configuracion", "razon_social", "text not null default 'Grupo Tecnológico Alameda SpA'"),
    ("configuracion", "rut_empresa", "text not null default '76.415.603-K'"),
    ("configuracion", "direccion_empresa", "text not null default 'Huérfanos 1055 dp 503, Santiago'"),
    ("configuracion", "email_finanzas", "text not null default 'finanzas@timer-crono.com'"),
    ("configuracion", "dias_pago", "integer not null default 5"),
    ("configuracion", "factor_nivel1", "real not null default 1.5"),
    ("configuracion", "factor_nivel2", "real not null default 1.0"),
    ("configuracion", "factor_nivel3", "real not null default 0.7"),
    ("evento_equipo", "funcion", "text not null default ''"),
    ("evento_equipo", "factor", "real"),
    ("eventos", "honorarios_aprobados", "boolean not null default false"),
    ("eventos", "aprobado_por", "text"),
    ("eventos", "aprobado_en", "text"),
    ("actividades", "etiqueta", "text not null default ''"),
    ("actividades", "carrera_texto", "text not null default ''"),
]

ESCENARIOS_PG = """create table if not exists escenarios (
  id          bigint generated always as identity primary key,
  nombre      text not null,
  codigo      text,
  parametros  text not null default '{}',
  excluidas   text not null default '[]',
  creado_por  text not null default '',
  creado_en   timestamptz not null default now()
)"""
ESCENARIOS_LOCAL = """create table if not exists escenarios (
  id          integer primary key autoincrement,
  nombre      text not null,
  codigo      text,
  parametros  text not null default '{}',
  excluidas   text not null default '[]',
  creado_por  text not null default '',
  creado_en   text not null default (datetime('now'))
)"""


def actualizar_estructura(conn) -> None:
    """Agrega columnas nuevas a bases creadas con una versión anterior de la app (no borra nada)."""
    motor = getattr(getattr(conn, "dialect", None), "name", "sqlite")
    if motor == "postgresql":
        _ejecutar(conn, "alter table eventos add column if not exists tasa_iva real not null default 19")
        _ejecutar(conn, """create table if not exists facturas (
  id               bigint generated always as identity primary key,
  evento_id        bigint not null references eventos(id),
  numero           text not null default '',
  fecha            date,
  cliente          text not null default '',
  rut_cliente      text not null default '',
  descripcion      text not null default '',
  neto             numeric(12,0) not null default 0 check (neto >= 0),
  iva              numeric(12,0) not null default 0 check (iva >= 0),
  total            numeric(12,0) not null default 0 check (total >= 0),
  pagada           boolean not null default false,
  fecha_pago       date,
  archivo_nombre   text,
  archivo          bytea,                    -- el PDF de la factura
  anulada          boolean not null default false,
  creado_en        timestamptz not null default now()
);
""")
        _ejecutar(conn, "create index if not exists facturas_por_evento on facturas (evento_id)")
        _ejecutar(conn, "alter table facturas enable row level security")
        _ejecutar(conn, """create table if not exists boletas (
  id             bigint generated always as identity primary key,
  evento_id      bigint not null references eventos(id) on delete cascade,
  codigo         text not null references personas(codigo),
  estado         text not null default 'pendiente'
                   check (estado in ('pendiente', 'solicitada', 'recibida', 'pagada')),
  numero         text not null default '',
  monto_bruto    numeric(12,0) not null default 0,
  archivo_nombre text,
  archivo        bytea,
  actualizado_en timestamptz not null default now(),
  unique (evento_id, codigo)
)""")
        _ejecutar(conn, "alter table boletas enable row level security")
        _ejecutar(conn, """create table if not exists funciones (
  id      bigint generated always as identity primary key,
  nombre  text not null unique,
  nivel   smallint not null default 2 check (nivel between 1 and 3),
  activo  boolean not null default true,
  orden   smallint not null default 0
)""")
        _ejecutar(conn, "alter table funciones enable row level security")
        _ejecutar(conn, ESCENARIOS_PG)
        _ejecutar(conn, "alter table escenarios enable row level security")
        for tabla, columna, tipo in COLUMNAS_NUEVAS:
            _ejecutar(conn, f"alter table {tabla} add column if not exists {columna} {tipo}")
        return
    _ejecutar(conn, ESCENARIOS_LOCAL)
    for tabla, columna, tipo in COLUMNAS_NUEVAS:
        columnas = {f["name"] for f in _filas(conn, f"pragma table_info({tabla})")}
        if columna not in columnas:
            _ejecutar(conn, f"alter table {tabla} add column {columna} {tipo}")


# ------------------------------------------------------------------ configuración
def configuracion(conn) -> dict | None:
    return _fila(conn, "select * from configuracion where id = 1")


def crear_configuracion(conn, nombre_empresa: str) -> None:
    _ejecutar(conn, "insert into configuracion (id, nombre_empresa) values (1, :n)", n=nombre_empresa)


CAMPOS_CONFIG = {"nombre_empresa", "pct_retencion", "base_reparto", "pct_empresa", "pct_director", "pct_equipo",
                 "razon_social", "rut_empresa", "direccion_empresa", "email_finanzas", "dias_pago",
                 "factor_nivel1", "factor_nivel2", "factor_nivel3"}


def guardar_configuracion(conn, **campos) -> None:
    campos = {k: v for k, v in campos.items() if k in CAMPOS_CONFIG}
    if campos:
        asignaciones = ", ".join(f"{k} = :{k}" for k in campos)
        _ejecutar(conn, f"update configuracion set {asignaciones} where id = 1", **campos)


# ------------------------------------------------------------------ personas
def personas(conn) -> list[dict]:
    return _filas(conn, """
        select codigo, nombre, cargo, tarifa_hora, activo, email, telefono,
               case when pin_hash is null then 0 else 1 end as tiene_pin
        from personas order by codigo""")


def persona_para_login(conn, codigo: str) -> dict | None:
    return _fila(conn, """
        select codigo, nombre, activo, pin_hash, intentos_fallidos, bloqueado_hasta
        from personas where codigo = :codigo""", codigo=codigo)


def guardar_intentos(conn, codigo: str, intentos: int, bloqueado_hasta: str | None) -> None:
    _ejecutar(conn, """
        update personas set intentos_fallidos = :intentos, bloqueado_hasta = :hasta
        where codigo = :codigo""", codigo=codigo, intentos=intentos, hasta=bloqueado_hasta)


def guardar_pin(conn, codigo: str, pin_hash: str) -> int:
    f = _fila(conn, """
        update personas set pin_hash = :pin_hash, intentos_fallidos = 0, bloqueado_hasta = null
        where codigo = :codigo returning codigo""", codigo=codigo, pin_hash=pin_hash)
    return 1 if f else 0


def crear_persona(conn, codigo: str, nombre: str, cargo: str, tarifa_hora: float) -> None:
    _ejecutar(conn, """
        insert into personas (codigo, nombre, cargo, tarifa_hora)
        values (:codigo, :nombre, :cargo, :tarifa)""",
              codigo=codigo, nombre=nombre, cargo=cargo, tarifa=tarifa_hora)


def actualizar_persona(conn, codigo: str, nombre: str, cargo: str, tarifa_hora: float, activo: bool) -> int:
    f = _fila(conn, """
        update personas set nombre = :nombre, cargo = :cargo, tarifa_hora = :tarifa, activo = :activo
        where codigo = :codigo returning codigo""",
              codigo=codigo, nombre=nombre, cargo=cargo, tarifa=tarifa_hora, activo=activo)
    return 1 if f else 0


# ------------------------------------------------------------------ categorías y productos
def categorias(conn) -> list[dict]:
    return _filas(conn, """
        select id, nombre, grupo, pagable_por_hora, tarifa_hora_especial, activo, orden
        from categorias order by orden, nombre""")


def crear_categoria(conn, nombre: str, grupo: str, pagable_por_hora: bool,
                    tarifa_hora_especial: float | None, orden: int = 0) -> None:
    _ejecutar(conn, """
        insert into categorias (nombre, grupo, pagable_por_hora, tarifa_hora_especial, orden)
        values (:nombre, :grupo, :pagable, :tarifa, :orden)""",
              nombre=nombre, grupo=grupo, pagable=pagable_por_hora, tarifa=tarifa_hora_especial, orden=orden)


def actualizar_categoria(conn, id_: int, nombre: str, grupo: str, pagable_por_hora: bool,
                         tarifa_hora_especial: float | None, activo: bool) -> None:
    _ejecutar(conn, """
        update categorias set nombre = :nombre, grupo = :grupo, pagable_por_hora = :pagable,
               tarifa_hora_especial = :tarifa, activo = :activo
        where id = :id""", id=id_, nombre=nombre, grupo=grupo, pagable=pagable_por_hora,
              tarifa=tarifa_hora_especial, activo=activo)


def productos(conn) -> list[dict]:
    return _filas(conn, "select id, nombre, activo, orden from productos order by orden, nombre")


def crear_producto(conn, nombre: str, orden: int = 0) -> None:
    _ejecutar(conn, "insert into productos (nombre, orden) values (:nombre, :orden)", nombre=nombre, orden=orden)


def actualizar_producto(conn, id_: int, nombre: str, activo: bool) -> None:
    _ejecutar(conn, "update productos set nombre = :nombre, activo = :activo where id = :id",
              id=id_, nombre=nombre, activo=activo)


# ------------------------------------------------------------------ eventos / carreras
_COLUMNAS_EVENTO = """id, nombre, fecha, cliente, producto_id, estado, venta_neta, tasa_iva, honorarios_aprobados,
                      aprobado_por, aprobado_en, base_reparto,
                      pct_empresa, pct_director, pct_equipo, hubspot_deal, notas"""


def eventos(conn) -> list[dict]:
    return _filas(conn, f"select {_COLUMNAS_EVENTO} from eventos order by fecha desc, id desc")


def evento(conn, id_: int) -> dict | None:
    return _fila(conn, f"select {_COLUMNAS_EVENTO} from eventos where id = :id", id=id_)


def gastos(conn) -> list[dict]:
    return _filas(conn, "select id, evento_id, tipo, descripcion, monto from evento_gastos order by id")


def equipo(conn) -> list[dict]:
    return _filas(conn, "select id, evento_id, codigo, rol, peso, funcion, factor from evento_equipo order by id")


def crear_evento(conn, datos: dict) -> int:
    f = _fila(conn, """
        insert into eventos (nombre, fecha, cliente, producto_id, estado, venta_neta, tasa_iva, base_reparto,
                             pct_empresa, pct_director, pct_equipo, hubspot_deal, notas)
        values (:nombre, :fecha, :cliente, :producto_id, :estado, :venta_neta, :tasa_iva, :base_reparto,
                :pct_empresa, :pct_director, :pct_equipo, :hubspot_deal, :notas)
        returning id""", **datos)
    return int(f["id"])


def actualizar_evento(conn, id_: int, datos: dict) -> None:
    _ejecutar(conn, """
        update eventos set nombre = :nombre, fecha = :fecha, cliente = :cliente,
               producto_id = :producto_id, estado = :estado, venta_neta = :venta_neta, tasa_iva = :tasa_iva,
               base_reparto = :base_reparto, pct_empresa = :pct_empresa, pct_director = :pct_director,
               pct_equipo = :pct_equipo, hubspot_deal = :hubspot_deal, notas = :notas
        where id = :id""", id=id_, **datos)


def reemplazar_gastos(conn, evento_id: int, lista: list[dict]) -> None:
    _ejecutar(conn, "delete from evento_gastos where evento_id = :id", id=evento_id)
    for g in lista:
        _ejecutar(conn, """
            insert into evento_gastos (evento_id, tipo, descripcion, monto)
            values (:evento_id, :tipo, :descripcion, :monto)""",
                  evento_id=evento_id, tipo=g["tipo"], descripcion=g.get("descripcion", ""), monto=g["monto"])


def reemplazar_equipo(conn, evento_id: int, lista: list[dict]) -> None:
    _ejecutar(conn, "delete from evento_equipo where evento_id = :id", id=evento_id)
    for i in lista:
        _ejecutar(conn, """
            insert into evento_equipo (evento_id, codigo, rol, peso, funcion, factor)
            values (:evento_id, :codigo, :rol, :peso, :funcion, :factor)""",
                  evento_id=evento_id, codigo=i["codigo"], rol=i["rol"], peso=i["peso"],
                  funcion=i.get("funcion") or "", factor=i.get("factor"))


# ------------------------------------------------------------------ actividades
_COLUMNAS_ACT = """id, codigo, fecha, categoria_id, producto_id, evento_id, cliente, descripcion,
                   horas, hora_inicio, hora_fin, estado, motivo_revision, revisado_por, anulada,
                   etiqueta, carrera_texto"""


def actividades_entre(conn, desde: str, hasta: str, codigo: str | None = None) -> list[dict]:
    """Actividades NO anuladas con desde <= fecha < hasta (fechas 'AAAA-MM-DD')."""
    return _filas(conn, f"""
        select {_COLUMNAS_ACT} from actividades
        where not anulada and fecha >= :desde and fecha < :hasta
          and (cast(:codigo as text) is null or codigo = :codigo)
        order by fecha, codigo, id""", desde=desde, hasta=hasta, codigo=codigo)


def actividades_de_evento(conn, evento_id: int) -> list[dict]:
    return _filas(conn, f"""
        select {_COLUMNAS_ACT} from actividades
        where not anulada and evento_id = :id order by fecha, id""", id=evento_id)


def actividades_por_revisar(conn) -> list[dict]:
    return _filas(conn, f"""
        select {_COLUMNAS_ACT} from actividades
        where not anulada and estado = 'pendiente' order by fecha, codigo, id""")


def insertar_actividad(conn, a: dict, creado_por: str) -> int:
    f = _fila(conn, """
        insert into actividades (codigo, fecha, categoria_id, producto_id, evento_id, cliente,
                                 descripcion, horas, hora_inicio, hora_fin, creado_por, etiqueta, carrera_texto)
        values (:codigo, :fecha, :categoria_id, :producto_id, :evento_id, :cliente,
                :descripcion, :horas, :hora_inicio, :hora_fin, :creado_por, :etiqueta, :carrera_texto)
        returning id""", creado_por=creado_por,
        **{"etiqueta": "", "carrera_texto": "", **a})
    return int(f["id"])


def actividades_de_dia_persona(conn, codigo: str, fecha: str) -> list[dict]:
    return _filas(conn, f"""select {_COLUMNAS_ACT} from actividades
        where not anulada and codigo = :codigo and fecha = :fecha order by id""", codigo=codigo, fecha=fecha)


def completar_etiqueta(conn, id_: int, etiqueta: str, carrera_texto: str) -> None:
    """Rellena etiqueta / carrera (texto) solo donde están vacías."""
    _ejecutar(conn, """update actividades set
        etiqueta = case when etiqueta = '' then :e else etiqueta end,
        carrera_texto = case when carrera_texto = '' then :c else carrera_texto end
        where id = :id""", e=etiqueta, c=carrera_texto, id=id_)


def cambiar_etiqueta(conn, id_: int, etiqueta: str) -> None:
    _ejecutar(conn, "update actividades set etiqueta = :e where id = :id", e=etiqueta, id=id_)


# ------------------------------------------------------------------ escenarios del simulador
def escenarios(conn, codigo: str | None) -> list[dict]:
    return _filas(conn, """select id, nombre, codigo, parametros, excluidas, creado_por, creado_en from escenarios
        where (cast(:codigo as text) is null and codigo is null) or codigo = :codigo
        order by id""", codigo=codigo)


def guardar_escenario(conn, nombre: str, codigo: str | None, parametros: str, excluidas: str, creado_por: str) -> int:
    f = _fila(conn, """insert into escenarios (nombre, codigo, parametros, excluidas, creado_por)
        values (:n, :c, :p, :x, :por) returning id""", n=nombre, c=codigo, p=parametros, x=excluidas, por=creado_por)
    return int(f["id"])


def borrar_escenario(conn, id_: int) -> None:
    _ejecutar(conn, "delete from escenarios where id = :id", id=id_)


def actividad(conn, id_: int) -> dict | None:
    return _fila(conn, f"select {_COLUMNAS_ACT} from actividades where id = :id", id=id_)


def anular_actividad(conn, id_: int) -> None:
    _ejecutar(conn, "update actividades set anulada = :si where id = :id", id=id_, si=True)


def revisar_actividad(conn, id_: int, estado: str, motivo: str, por: str, en: str) -> None:
    _ejecutar(conn, """
        update actividades set estado = :estado, motivo_revision = :motivo,
               revisado_por = :por, revisado_en = :en
        where id = :id and not anulada""", id=id_, estado=estado, motivo=motivo, por=por, en=en)


# ------------------------------------------------------------------ facturas
_COLUMNAS_FACTURA = """id, evento_id, numero, fecha, cliente, rut_cliente, descripcion, neto, iva, total,
                       pagada, fecha_pago, archivo_nombre"""


def facturas(conn, evento_id: int | None = None) -> list[dict]:
    return _filas(conn, f"""
        select {_COLUMNAS_FACTURA} from facturas
        where not anulada and (cast(:evento_id as integer) is null or evento_id = :evento_id)
        order by fecha, id""", evento_id=evento_id)


def factura_por_numero(conn, numero: str) -> dict | None:
    return _fila(conn, f"select {_COLUMNAS_FACTURA} from facturas where not anulada and numero = :n", n=numero)


def insertar_factura(conn, f: dict) -> int:
    fila = _fila(conn, """
        insert into facturas (evento_id, numero, fecha, cliente, rut_cliente, descripcion, neto, iva, total,
                              pagada, fecha_pago, archivo_nombre, archivo)
        values (:evento_id, :numero, :fecha, :cliente, :rut_cliente, :descripcion, :neto, :iva, :total,
                :pagada, :fecha_pago, :archivo_nombre, :archivo)
        returning id""", **f)
    return int(fila["id"])


def marcar_pago_factura(conn, id_: int, pagada: bool, fecha_pago: str | None) -> None:
    _ejecutar(conn, "update facturas set pagada = :p, fecha_pago = :f where id = :id",
              id=id_, p=pagada, f=fecha_pago)


def anular_factura(conn, id_: int) -> None:
    _ejecutar(conn, "update facturas set anulada = :si where id = :id", id=id_, si=True)


def archivo_factura(conn, id_: int) -> dict | None:
    return _fila(conn, "select archivo_nombre, archivo from facturas where id = :id", id=id_)


def fijar_venta_evento(conn, id_: int, venta_neta: float, tasa_iva: float) -> None:
    _ejecutar(conn, "update eventos set venta_neta = :v, tasa_iva = :t where id = :id",
              id=id_, v=venta_neta, t=tasa_iva)


# ------------------------------------------------------------------ edición y borrado
def actualizar_actividad(conn, id_: int, a: dict) -> None:
    _ejecutar(conn, """
        update actividades set fecha = :fecha, categoria_id = :categoria_id, producto_id = :producto_id,
               evento_id = :evento_id, cliente = :cliente, descripcion = :descripcion, horas = :horas
        where id = :id""", id=id_, **a)


def borrar_evento(conn, id_: int) -> None:
    """Borra la carrera con sus gastos, equipo y facturas. Las horas cargadas a ella se conservan (sin carrera)."""
    _ejecutar(conn, "update actividades set evento_id = null where evento_id = :id", id=id_)
    _ejecutar(conn, "delete from facturas where evento_id = :id", id=id_)
    _ejecutar(conn, "delete from boletas where evento_id = :id", id=id_)
    _ejecutar(conn, "delete from evento_gastos where evento_id = :id", id=id_)
    _ejecutar(conn, "delete from evento_equipo where evento_id = :id", id=id_)
    _ejecutar(conn, "delete from eventos where id = :id", id=id_)


def borrar_movimientos(conn) -> None:
    """MODO PRUEBA: borra horas, carreras y facturas (deja personas, categorías y ajustes)."""
    for tabla in ("actividades", "facturas", "boletas", "evento_gastos", "evento_equipo", "eventos"):
        _ejecutar(conn, f"delete from {tabla}")


def guardar_contacto(conn, codigo: str, email: str, telefono: str) -> None:
    _ejecutar(conn, "update personas set email = :e, telefono = :t where codigo = :c", c=codigo, e=email, t=telefono)


# ------------------------------------------------------------------ boletas de honorarios por carrera
def boletas(conn, evento_id: int | None = None, codigo: str | None = None) -> list[dict]:
    return _filas(conn, """
        select id, evento_id, codigo, estado, numero, monto_bruto, archivo_nombre
        from boletas
        where (cast(:evento_id as integer) is null or evento_id = :evento_id)
          and (cast(:codigo as text) is null or codigo = :codigo)""", evento_id=evento_id, codigo=codigo)


def guardar_boleta(conn, evento_id: int, codigo: str, estado: str, numero: str, monto_bruto: float,
                   archivo_nombre: str | None = None, archivo: bytes | None = None) -> None:
    existe = _fila(conn, "select id from boletas where evento_id = :e and codigo = :c", e=evento_id, c=codigo)
    if existe is None:
        _ejecutar(conn, """
            insert into boletas (evento_id, codigo, estado, numero, monto_bruto, archivo_nombre, archivo)
            values (:e, :c, :estado, :numero, :monto, :an, :a)""",
                  e=evento_id, c=codigo, estado=estado, numero=numero, monto=monto_bruto, an=archivo_nombre, a=archivo)
    else:
        _ejecutar(conn, """
            update boletas set estado = :estado, numero = :numero, monto_bruto = :monto,
                   archivo_nombre = coalesce(:an, archivo_nombre), archivo = coalesce(:a, archivo)
            where id = :id""", id=existe["id"], estado=estado, numero=numero, monto=monto_bruto,
                  an=archivo_nombre, a=archivo)


def archivo_boleta(conn, evento_id: int, codigo: str) -> dict | None:
    return _fila(conn, "select archivo_nombre, archivo from boletas where evento_id = :e and codigo = :c",
                 e=evento_id, c=codigo)


# ------------------------------------------------------------------ funciones dentro de una carrera
def funciones(conn) -> list[dict]:
    return _filas(conn, "select id, nombre, nivel, activo, orden from funciones order by nivel, orden, nombre")


def crear_funcion(conn, nombre: str, nivel: int, orden: int = 0) -> None:
    _ejecutar(conn, "insert into funciones (nombre, nivel, orden) values (:n, :nivel, :o)", n=nombre, nivel=nivel, o=orden)


def reemplazar_funciones(conn, lista: list[dict]) -> None:
    _ejecutar(conn, "delete from funciones")
    for i, f in enumerate(lista):
        _ejecutar(conn, "insert into funciones (nombre, nivel, activo, orden) values (:n, :nivel, :a, :o)",
                  n=f["nombre"], nivel=f["nivel"], a=f.get("activo", True), o=i)


def aprobar_honorarios(conn, id_: int, aprobado: bool, por: str | None, en: str | None) -> None:
    _ejecutar(conn, "update eventos set honorarios_aprobados = :a, aprobado_por = :p, aprobado_en = :e where id = :id",
              id=id_, a=aprobado, p=por, e=en)
