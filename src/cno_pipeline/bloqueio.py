# Exclusão mútua por snapshot, para que duas execuções não se atropelem.

from __future__ import annotations

import contextlib
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path


class SnapshotOcupado(RuntimeError):
    """Outra execução já detém a trava deste snapshot."""


def _tentar_travar(fd: int) -> bool:
    """Tenta a trava exclusiva sem bloquear. Devolve se conseguiu.

    As duas implementações têm a propriedade que interessa, a trava morre com o
    processo, sem depender de nenhuma limpeza nossa.
    """
    if os.name == "nt":
        import msvcrt

        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    import fcntl

    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _quem_detem(registro: Path) -> str:
    """Descrição do detentor atual, para a mensagem de erro. Melhor esforço."""
    try:
        texto = registro.read_text(encoding="utf-8").strip()
    except OSError:
        texto = ""
    return texto or "processo desconhecido (o registro não pôde ser lido)"


@contextmanager
def travar_snapshot(
    data_dir: Path,
    snapshot_id: str,
    *,
    etapa: str,
    espera_segundos: float = 0.0,
) -> Iterator[Path]:
    """Trava exclusiva do snapshot enquanto o bloco roda.

    Levanta `SnapshotOcupado` se outra execução a detém e `espera_segundos` se
    esgota.
    """
    pasta = data_dir / "_locks"
    pasta.mkdir(parents=True, exist_ok=True)
    trava = pasta / f"snapshot_date={snapshot_id}.lock"
    registro = pasta / f"snapshot_date={snapshot_id}.quem"

    fd = os.open(trava, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        limite = time.monotonic() + espera_segundos
        while not _tentar_travar(fd):
            if time.monotonic() >= limite:
                raise SnapshotOcupado(
                    f"o snapshot {snapshot_id} já está sendo processado por outra "
                    f"execução: {_quem_detem(registro)}.\n"
                    "Duas execuções sobre o mesmo snapshot corromperiam a partição "
                    "em silêncio, então esta foi recusada.\n"
                    "Espere a outra terminar, ou rode com um snapshot diferente."
                )
            time.sleep(0.25)

        quem = f"{etapa} · pid {os.getpid()} · desde {datetime.now(UTC):%Y-%m-%d %H:%M:%SZ}"
        with contextlib.suppress(OSError):
            registro.write_text(quem + "\n", encoding="utf-8")

        yield trava
    finally:
        with contextlib.suppress(OSError):
            registro.unlink(missing_ok=True)
        os.close(fd)
