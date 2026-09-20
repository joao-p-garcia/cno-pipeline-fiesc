"""Exclusão mútua por snapshot, para que duas execuções não se atropelem.

**O problema, medido.** `cno transform` e `cno curate` reescrevem a partição do
snapshot em dois passos: `shutil.rmtree(particao)` e, logo depois, um `COPY ...
PARTITION_BY`. Entre um e outro há uma janela. Duas execuções sobre o mesmo
snapshot dentro dessa janela produzem uma partição pela metade — e o modo de
falha é o pior possível, porque **não levanta exceção**: o `COPY` termina bem, o
parquet é legível, e só a contagem denuncia, se alguém conferir.

Isso não é hipótese. Uma task órfã no Airflow já deixou duas execuções se
sobreporem neste projeto; não mordeu por sorte de escalonamento.

**Por que não bastava o `max_active_runs`.** Ele é do orquestrador, e a garantia
tem de valer para quem roda o comando na mão, para dois terminais abertos, para
um `airflow tasks run` avulso e para o container. Uma trava dentro da etapa
protege independentemente de quem a chamou — que era o ponto registrado como
pendência desde o início.

**Por que `flock` e não um arquivo de PID.** Um arquivo-sentinela criado com
`O_EXCL` vira lixo permanente quando o processo morre sem limpar: a próxima
execução encontra a trava de um processo que não existe mais e recusa rodar, e
alguém precisa apagar à mão. O bloqueio do sistema operacional é liberado pelo
próprio kernel quando o descritor fecha, **inclusive se o processo for morto com
`SIGKILL` ou o container cair**. Não existe trava órfã aqui.

**O escopo é o snapshot, não a etapa.** `transform` e `curate` disputam a mesma
trava de propósito: além de cada um poder atropelar a si mesmo, a curadoria *lê*
a staging que o tratamento reescreve. Snapshots diferentes têm travas diferentes
e seguem em paralelo à vontade.

**A trava não bloqueia por padrão.** Uma etapa que espera indefinidamente vira
uma task pendurada, que é mais difícil de diagnosticar do que uma que falha
dizendo o motivo. Quem quiser enfileirar passa `espera_segundos`.
"""

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

    As duas implementações têm a propriedade que interessa: a trava morre com o
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

    A trava fica em `data_dir/_locks`, e não dentro de `staging/` ou `curated/`,
    porque ela cobre as duas camadas — e porque `make clean-data` apaga camada,
    não deve apagar trava de execução em curso.

    Levanta `SnapshotOcupado` se outra execução a detém e `espera_segundos` se
    esgota.
    """
    pasta = data_dir / "_locks"
    pasta.mkdir(parents=True, exist_ok=True)
    trava = pasta / f"snapshot_date={snapshot_id}.lock"
    registro = pasta / f"snapshot_date={snapshot_id}.quem"

    # O arquivo de trava nunca é apagado. Apagar abre uma corrida clássica: quem
    # apaga pode remover o arquivo que outro processo acabou de abrir e travar,
    # e os dois passam a travar inodes diferentes — dois donos ao mesmo tempo,
    # sem erro nenhum. Um arquivo vazio por snapshot é barato.
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

        # Só depois de ter a trava: quem não a tem não pode escrever aqui.
        quem = f"{etapa} · pid {os.getpid()} · desde {datetime.now(UTC):%Y-%m-%d %H:%M:%SZ}"
        # O registro é conveniência de diagnóstico; a trava é o contrato, e não
        # conseguir anotar quem a detém não pode impedir a execução de rodar.
        with contextlib.suppress(OSError):
            registro.write_text(quem + "\n", encoding="utf-8")

        yield trava
    finally:
        with contextlib.suppress(OSError):
            registro.unlink(missing_ok=True)
        # Fechar o descritor libera a trava — é isto que torna impossível uma
        # trava órfã, e por isso não há `flock(LOCK_UN)` explícito aqui.
        os.close(fd)
