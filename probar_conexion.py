"""Prueba rápida: ¿la app puede hablar con la base de datos de Supabase?

Uso (en la Terminal, dentro de la carpeta timer_horas_app):
    python3 probar_conexion.py
No cambia ningún dato: solo lee.
"""
import os
import sys

RUTA = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".streamlit", "secrets.toml")
TABLAS = ["configuracion", "personas", "categorias", "productos", "eventos", "evento_gastos",
          "evento_equipo", "actividades"]


def leer_secretos() -> dict:
    try:
        import tomllib
        with open(RUTA, "rb") as f:
            return tomllib.load(f)
    except ModuleNotFoundError:
        import toml  # viene con Streamlit
        return toml.load(RUTA)


def explicar(error: Exception) -> str:
    t = str(error).lower()
    if "password authentication failed" in t:
        return "La contraseña de la base de datos no es correcta. Vuelve a correr crear_secretos.py."
    if "tenant or user not found" in t:
        return "El usuario no es correcto. Debe ser 'postgres.' + el código del proyecto (Session pooler)."
    if "could not translate host name" in t or "nodename nor servname" in t:
        return "No se encontró el host. Revisa que esté bien copiado y que tengas internet."
    if "timeout" in t or "timed out" in t:
        return "Supabase no respondió. Revisa tu internet, o si el proyecto está pausado en Supabase."
    return "Error no reconocido. Copia el mensaje de arriba y envíaselo a Claude (sin contraseñas)."


def main() -> int:
    print("\n=== Prueba de conexión con Supabase ===\n")
    if not os.path.exists(RUTA):
        print("✗ No existe el archivo secreto (la app está en MODO PRUEBA LOCAL).")
        print("  Para usar Supabase corre primero:  python3 crear_secretos.py")
        return 1
    secretos = leer_secretos()
    if "basedatos" not in secretos:
        print("✗ Al archivo secreto le falta la parte [basedatos]. Vuelve a correr crear_secretos.py")
        return 1
    print(f"✓ Archivo secreto encontrado ({len(secretos.get('usuarios', {}))} usuario(s) de administración)")

    try:
        from sqlalchemy import create_engine, text
        from sqlalchemy.engine import URL
        import psycopg2  # noqa: F401
    except ModuleNotFoundError as e:
        print(f"✗ Falta un paquete de Python ({e.name}). Corre:  python3 -m pip install -r requirements.txt")
        return 1
    print("✓ Paquetes de Python instalados")

    c = secretos["basedatos"]
    url = URL.create("postgresql+psycopg2", username=c["usuario"], password=c["contrasena"],
                     host=c["host"], port=int(c.get("puerto", 5432)), database=c.get("nombre", "postgres"))
    try:
        motor = create_engine(url, connect_args={"sslmode": "require", "connect_timeout": 10})
        with motor.connect() as conn:
            existentes = {r[0] for r in conn.execute(text(
                "select table_name from information_schema.tables where table_schema = 'public'"))}
    except Exception as e:  # noqa: BLE001
        print(f"✗ No se pudo conectar.\n  Mensaje: {str(e).splitlines()[0]}")
        print(f"  Qué hacer: {explicar(e)}")
        return 1

    print("✓ Conectado a Supabase")
    faltan = [t for t in TABLAS if t not in existentes]
    if faltan:
        print(f"✗ Faltan tablas: {', '.join(faltan)}")
        print("  Pega basedatos/crear_base_de_datos.sql en Supabase → SQL Editor → Run.")
        return 1
    print("✓ Todas las tablas están creadas")
    print("\nTODO OK. Ya puedes abrir la app con:  streamlit run app.py\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
