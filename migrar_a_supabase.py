"""Copia los datos de la app local (datos_local/timer_local.db) a Supabase.

Uso (en la Terminal, dentro de la carpeta timer_horas_app), DESPUÉS de crear_secretos.py y probar_conexion.py:
    python3 migrar_a_supabase.py

Qué hace:
1. Muestra cuántas filas hay en cada tabla, en tu Mac y en Supabase.
2. Si escribes COPIAR, vacía las tablas de Supabase y copia todo lo de tu Mac (mismos ids).
Tu base local no se toca. Se puede repetir las veces que quieras.
"""
import os
import sqlite3
import sys

CARPETA = os.path.dirname(os.path.abspath(__file__))
RUTA_SECRETOS = os.path.join(CARPETA, ".streamlit", "secrets.toml")
RUTA_LOCAL = os.path.join(CARPETA, "datos_local", "timer_local.db")
# Orden en que se copian (primero las tablas de las que dependen otras)
TABLAS = ["configuracion", "personas", "categorias", "productos", "funciones", "eventos", "evento_gastos",
          "evento_equipo", "facturas", "boletas", "actividades", "escenarios"]


def leer_secretos() -> dict:
    try:
        import tomllib
        with open(RUTA_SECRETOS, "rb") as f:
            return tomllib.load(f)
    except ModuleNotFoundError:
        import toml
        return toml.load(RUTA_SECRETOS)


def tablas_local(db) -> set:
    return {r[0] for r in db.execute("select name from sqlite_master where type = 'table'")}


def columnas_local(db, tabla) -> list:
    return [r[1] for r in db.execute(f"pragma table_info({tabla})")]


def convertir(valor, tipo_pg, psycopg2):
    if valor is None:
        return None
    if tipo_pg == "boolean":
        return bool(valor)
    if tipo_pg == "bytea":
        return psycopg2.Binary(valor)
    return valor


def main() -> int:
    print("\n=== Copiar datos de tu Mac a Supabase ===\n")
    if not os.path.exists(RUTA_SECRETOS):
        print("✗ Falta el archivo secreto. Corre primero:  python3 crear_secretos.py")
        return 1
    if not os.path.exists(RUTA_LOCAL):
        print("✗ No encontré la base local (datos_local/timer_local.db). No hay nada que copiar.")
        return 1
    import psycopg2
    c = leer_secretos()["basedatos"]
    pg = psycopg2.connect(host=c["host"], port=int(c.get("puerto", 5432)), user=c["usuario"],
                          password=c["contrasena"], dbname=c.get("nombre", "postgres"), sslmode="require",
                          connect_timeout=15)
    db = sqlite3.connect(RUTA_LOCAL)
    cur = pg.cursor()
    cur.execute("select table_name, column_name, data_type, is_identity from information_schema.columns "
                "where table_schema = 'public'")
    info: dict = {}
    for t, col, tipo, ident in cur.fetchall():
        info.setdefault(t, {})[col] = (tipo, ident == "YES")
    faltan = [t for t in TABLAS if t not in info]
    if faltan:
        print(f"✗ En Supabase faltan tablas: {', '.join(faltan)}.")
        print("  Corre basedatos/crear_base_de_datos.sql en el SQL Editor de Supabase y vuelve a intentar.")
        return 1
    locales = tablas_local(db)
    plan = []
    print(f"{'Tabla':<16}{'En tu Mac':>10}{'En Supabase':>13}")
    for t in TABLAS:
        n_local = db.execute(f"select count(*) from {t}").fetchone()[0] if t in locales else 0
        cur.execute(f"select count(*) from {t}")
        n_pg = cur.fetchone()[0]
        print(f"{t:<16}{n_local:>10}{n_pg:>13}")
        if t in locales:
            plan.append(t)
    print("\nSi sigues, se BORRA lo que hay en Supabase en estas tablas y se reemplaza por lo de tu Mac.")
    if input("Escribe COPIAR para seguir (cualquier otra cosa cancela): ").strip() != "COPIAR":
        print("Cancelado. No se cambió nada.")
        return 0
    try:
        cur.execute("truncate " + ", ".join(TABLAS) + " restart identity cascade")
        for t in plan:
            cols = [col for col in columnas_local(db, t) if col in info[t]]
            filas = db.execute(f"select {', '.join(cols)} from {t}").fetchall()
            if not filas:
                continue
            identidad = any(info[t][col][1] for col in cols)
            sql = (f"insert into {t} ({', '.join(cols)}) "
                   + ("overriding system value " if identidad else "")
                   + f"values ({', '.join(['%s'] * len(cols))})")
            datos = [tuple(convertir(v, info[t][col][0], psycopg2) for v, col in zip(f, cols)) for f in filas]
            cur.executemany(sql, datos)
            for col in cols:
                if info[t][col][1]:
                    cur.execute(f"select setval(pg_get_serial_sequence('{t}', '{col}'), "
                                f"coalesce((select max({col}) from {t}), 1), "
                                f"(select max({col}) from {t}) is not null)")
            print(f"✓ {t}: {len(filas)} fila(s)")
        pg.commit()
    except Exception as e:  # noqa: BLE001
        pg.rollback()
        print(f"\n✗ Algo falló y no se copió nada: {type(e).__name__}: {e}")
        print("  Copia este mensaje y envíaselo a Claude (no tiene contraseñas).")
        return 1
    finally:
        db.close()
    print("\nListo: Supabase tiene ahora los mismos datos que tu Mac.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nCancelado. No se cambió nada.")
        sys.exit(1)
