"""Conexión de prueba sobre SQLite en memoria, con la misma forma que una conexión de SQLAlchemy
(conn.execute(consulta, parametros).mappings().all() / .first()). Así se prueban los servicios
sin instalar nada ni tocar Supabase."""
import sqlite3
from pathlib import Path

ESQUEMA = Path(__file__).resolve().parent.parent / "basedatos" / "esquema_local.sql"


class _Resultado:
    def __init__(self, cursor):
        self._filas = cursor.fetchall() if cursor.description else []

    def mappings(self):
        return self

    def all(self):
        return [dict(f) for f in self._filas]

    def first(self):
        return dict(self._filas[0]) if self._filas else None


class ConexionPrueba:
    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(ESQUEMA.read_text(encoding="utf-8"))

    def execute(self, consulta, parametros=None):
        return _Resultado(self.db.execute(str(consulta), parametros or {}))
