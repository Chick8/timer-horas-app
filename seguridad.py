"""Cifrado de PIN de personas y contraseñas de administración (igual que en la app de asistencia).

Nunca se guarda el PIN ni la contraseña: solo una "huella" (hash) con sal aleatoria.
Para comprobar, se recalcula la huella con lo que escribió la persona y se compara.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

ALGORITMO = "pbkdf2_sha256"
ITERACIONES = 200_000


def hash_secreto(texto: str) -> str:
    sal = secrets.token_hex(16)
    huella = hashlib.pbkdf2_hmac("sha256", texto.encode("utf-8"), sal.encode("ascii"), ITERACIONES)
    return f"{ALGORITMO}${ITERACIONES}${sal}${huella.hex()}"


def verificar_secreto(texto: str, guardado: str | None) -> bool:
    if not texto or not guardado:
        return False
    try:
        algoritmo, iteraciones, sal, huella = guardado.split("$")
        if algoritmo != ALGORITMO:
            return False
        calculada = hashlib.pbkdf2_hmac("sha256", texto.encode("utf-8"), sal.encode("ascii"), int(iteraciones))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(calculada.hex(), huella)


def pin_valido(pin: str) -> tuple[bool, str]:
    """Reglas del PIN: 4 dígitos, y no algo demasiado obvio."""
    if not pin or not pin.isdigit() or len(pin) != 4:
        return False, "El PIN debe tener exactamente 4 números."
    if len(set(pin)) == 1 or pin in ("1234", "4321", "0123", "1212"):
        return False, "Ese PIN es muy fácil de adivinar. Elige otro."
    return True, "OK"
