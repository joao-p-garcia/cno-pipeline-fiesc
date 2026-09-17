"""Utilidades pequenas compartilhadas entre as etapas do pipeline."""

from __future__ import annotations


def formatar_bytes(n: int | None) -> str:
    """Formata um tamanho em bytes de forma legível em log."""
    if n is None:
        return "desconhecido"
    valor = float(n)
    for unidade in ("B", "KB", "MB", "GB", "TB"):
        if valor < 1024:
            return f"{valor:.1f} {unidade}"
        valor /= 1024
    return f"{valor:.1f} PB"
