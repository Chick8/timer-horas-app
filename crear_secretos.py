"""Crea el archivo secreto .streamlit/secrets.toml haciéndote preguntas.

Uso (en la Terminal, dentro de la carpeta timer_horas_app):
    python3 crear_secretos.py

Solo hace falta cuando pases de MODO PRUEBA LOCAL a Supabase (datos en la nube, compartidos
por todo el equipo). El archivo guarda la conexión y las contraseñas de administración
(cifradas). NUNCA se sube a GitHub (está en .gitignore) ni se comparte por chat.
"""
from __future__ import annotations

import getpass
import json
import os
import sys

from seguridad import hash_secreto

CARPETA = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".streamlit")
RUTA = os.path.join(CARPETA, "secrets.toml")


def preguntar(texto: str, defecto: str | None = None) -> str:
    sufijo = f" [{defecto}]" if defecto else ""
    while True:
        r = input(f"{texto}{sufijo}: ").strip()
        if r:
            return r
        if defecto is not None:
            return defecto
        print("   (no puede quedar vacío)")


def clave_nueva(texto: str, minimo: int = 8) -> str:
    while True:
        a = getpass.getpass(f"{texto} (no se ve mientras escribes): ")
        if len(a) < minimo:
            print(f"   Debe tener al menos {minimo} caracteres.")
            continue
        if getpass.getpass("   Repítela: ") == a:
            return a
        print("   No coinciden. Intenta de nuevo.")


def t(valor) -> str:
    """Texto en formato TOML (comillas y caracteres especiales escapados)."""
    return json.dumps(valor, ensure_ascii=False)


def main() -> None:
    print("\n=== Configuración secreta de Horas TIMER ===\n")
    if os.path.exists(RUTA):
        if preguntar("Ya existe un archivo secreto. ¿Reemplazarlo? (s/n)", "n").lower() != "s":
            print("No se cambió nada.")
            return

    print("PARTE 1 — Conexión a Supabase (proyecto NUEVO, distinto al del restaurante)")
    print("  En Supabase, abre el proyecto y aprieta el botón 'Connect' (arriba).")
    print("  Elige el método 'Session pooler' y abre 'View parameters'.")
    print("  Copia de ahí cada dato que te pido:\n")
    host = preguntar("  host (termina en pooler.supabase.com)")
    if "pooler.supabase.com" not in host:
        print("   OJO: ese host no parece del 'Session pooler'. Streamlit Cloud solo funciona con el pooler.")
    puerto = preguntar("  port", "5432")
    usuario = preguntar("  user (empieza con postgres.)")
    if not usuario.startswith("postgres."):
        print("   OJO: con el pooler, el usuario suele ser 'postgres.' seguido del código de tu proyecto.")
    base = preguntar("  database", "postgres")
    contrasena = getpass.getpass("  Contraseña de la base de datos (la que guardaste al crear el proyecto; "
                                 "no se ve mientras escribes): ")

    print("\nPARTE 2 — Usuarios de administración (para entrar a ?modo=admin)")
    usuarios = []
    while True:
        defecto = "gabriel" if not usuarios else None
        u = preguntar("  Usuario (minúsculas, sin espacios)", defecto).lower().replace(" ", "")
        nombre = preguntar("  Nombre que se muestra", u.capitalize())
        clave = clave_nueva(f"  Contraseña para {u}")
        usuarios.append((u, nombre, hash_secreto(clave)))
        if preguntar("  ¿Agregar otro usuario? (s/n)", "n").lower() != "s":
            break

    lineas = [
        "# Archivo SECRETO de Horas TIMER. No subir a GitHub ni compartir.",
        "# Creado con crear_secretos.py. Para Streamlit Cloud: copiar TODO este texto",
        "# en la app → Settings → Secrets.",
        "",
        "[basedatos]",
        f"host = {t(host)}",
        f"puerto = {int(puerto)}",
        f"usuario = {t(usuario)}",
        f"contrasena = {t(contrasena)}",
        f"nombre = {t(base)}",
    ]
    for u, nombre, h in usuarios:
        lineas += ["", f"[usuarios.{u}]", f"nombre = {t(nombre)}", f"hash = {t(h)}", 'rol = "admin"']

    os.makedirs(CARPETA, exist_ok=True)
    with open(RUTA, "w", encoding="utf-8") as f:
        f.write("\n".join(lineas) + "\n")
    os.chmod(RUTA, 0o600)
    print(f"\nListo: se creó {RUTA}")
    print("Siguiente paso:  python3 probar_conexion.py\n")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelado. No se cambió nada.")
        sys.exit(1)
