"""Testes da exclusão mútua por snapshot.

A corrida que isto previne não dá erro: duas execuções sobre o mesmo snapshot
produzem uma partição pela metade que é parquet válido e legível. Não dá para
testar o sintoma, então testa-se o mecanismo — e, no fim, que a etapa de fato
recusa rodar duas vezes em paralelo.

O teste de contenção roda em **processo separado**, não em duas threads: o
`flock` do POSIX é do descritor aberto, e dois `open()` no mesmo processo já
conflitam, mas um subprocesso prova também que a trava sobrevive à fronteira de
processo, que é o caso real (dois `cno transform`, ou um deles órfão).
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from cno_pipeline.bloqueio import SnapshotOcupado, travar_snapshot

SNAPSHOT = "2026-09-12"


def _segurar_em_subprocesso(data_dir: Path, snapshot: str, sinal: Path) -> subprocess.Popen:
    """Sobe um processo que toma a trava e a segura até ser morto."""
    codigo = textwrap.dedent(f"""
        import pathlib, time, sys
        sys.path.insert(0, {str(Path(__file__).resolve().parents[1] / "src")!r})
        from cno_pipeline.bloqueio import travar_snapshot
        with travar_snapshot(pathlib.Path({str(data_dir)!r}), {snapshot!r}, etapa="refem"):
            pathlib.Path({str(sinal)!r}).write_text("peguei")
            time.sleep(60)
    """)
    processo = subprocess.Popen([sys.executable, "-c", codigo])
    for _ in range(200):
        if sinal.is_file():
            return processo
        time.sleep(0.05)
    processo.kill()
    raise AssertionError("o subprocesso não conseguiu tomar a trava")


def test_trava_e_liberada_ao_sair_do_bloco(tmp_path: Path):
    """Duas execuções em sequência nunca se estorvam."""
    for _ in range(3):
        with travar_snapshot(tmp_path, SNAPSHOT, etapa="teste"):
            pass


def test_segunda_execucao_no_mesmo_snapshot_e_recusada(tmp_path: Path):
    """O caso que motivou tudo: duas execuções, mesmo snapshot."""
    sinal = tmp_path / "peguei"
    refem = _segurar_em_subprocesso(tmp_path, SNAPSHOT, sinal)
    try:
        with (
            pytest.raises(SnapshotOcupado) as erro,
            travar_snapshot(tmp_path, SNAPSHOT, etapa="cno transform"),
        ):
            pytest.fail("a segunda execução não deveria ter conseguido a trava")
        # A mensagem precisa dizer o que fazer, não só que falhou.
        assert SNAPSHOT in str(erro.value)
        assert "refem" in str(erro.value), "a mensagem não identifica quem detém a trava"
    finally:
        refem.kill()
        refem.wait(timeout=10)


def test_snapshots_diferentes_nao_se_estorvam(tmp_path: Path):
    """Reprocessar ontem enquanto hoje roda é legítimo, e tem de continuar sendo."""
    sinal = tmp_path / "peguei"
    refem = _segurar_em_subprocesso(tmp_path, "2026-09-11", sinal)
    try:
        with travar_snapshot(tmp_path, "2026-09-12", etapa="cno transform"):
            pass
    finally:
        refem.kill()
        refem.wait(timeout=10)


def test_trava_morre_com_o_processo(tmp_path: Path):
    """A razão de usar `flock` em vez de arquivo-sentinela.

    O processo é morto com `SIGKILL`, sem chance de limpar nada. Se a trava
    fosse um arquivo criado com `O_EXCL`, ela ficaria para sempre e a próxima
    execução legítima seria recusada até alguém apagar à mão.
    """
    sinal = tmp_path / "peguei"
    refem = _segurar_em_subprocesso(tmp_path, SNAPSHOT, sinal)
    refem.kill()
    refem.wait(timeout=10)

    # Sem nenhuma limpeza, a trava tem de estar livre.
    with travar_snapshot(tmp_path, SNAPSHOT, etapa="depois do kill"):
        pass


def test_espera_desiste_com_mensagem_em_vez_de_pendurar(tmp_path: Path):
    """Uma task pendurada é pior de diagnosticar do que uma que falha explicando."""
    sinal = tmp_path / "peguei"
    refem = _segurar_em_subprocesso(tmp_path, SNAPSHOT, sinal)
    try:
        inicio = time.monotonic()
        with (
            pytest.raises(SnapshotOcupado),
            travar_snapshot(tmp_path, SNAPSHOT, etapa="teste", espera_segundos=0.6),
        ):
            pass
        decorrido = time.monotonic() - inicio
        assert 0.5 <= decorrido < 10, f"esperou {decorrido:.1f}s, fora do previsto"
    finally:
        refem.kill()
        refem.wait(timeout=10)


def test_o_arquivo_de_trava_nao_e_apagado(tmp_path: Path):
    """Apagar o arquivo abriria a corrida que a trava existe para fechar.

    Se cada execução apagasse o arquivo ao sair, uma poderia remover o inode que
    outra acabou de abrir e travar: os dois passariam a travar arquivos
    diferentes e ambos se achariam donos, sem erro nenhum.
    """
    with travar_snapshot(tmp_path, SNAPSHOT, etapa="teste"):
        pass
    trava = tmp_path / "_locks" / f"snapshot_date={SNAPSHOT}.lock"
    assert trava.is_file(), "o arquivo de trava foi apagado ao sair do bloco"


def test_registro_de_quem_detem_some_ao_liberar(tmp_path: Path):
    """O registro é de diagnóstico: existe enquanto a trava existe, e some junto."""
    registro = tmp_path / "_locks" / f"snapshot_date={SNAPSHOT}.quem"
    with travar_snapshot(tmp_path, SNAPSHOT, etapa="cno curate"):
        assert registro.is_file()
        conteudo = registro.read_text(encoding="utf-8")
        assert "cno curate" in conteudo
        assert str(os.getpid()) in conteudo
    assert not registro.exists()


# ---------------------------------------------------------------------------
# A etapa de verdade, não só o mecanismo
# ---------------------------------------------------------------------------


def test_transform_recusa_rodar_com_o_snapshot_travado(camada_raw, monkeypatch):
    """O que o usuário vê: `cno transform` falha explicando, em vez de corromper.

    Este é o teste que amarra o mecanismo à etapa. Sem ele, alguém poderia
    remover o `with` de `executar_staging` e os sete testes acima continuariam
    verdes, porque testam a trava, não o seu uso.
    """
    from cno_pipeline.transform import executar_staging

    sinal = camada_raw.data_dir / "peguei"
    refem = _segurar_em_subprocesso(camada_raw.data_dir, SNAPSHOT, sinal)
    try:
        with pytest.raises(SnapshotOcupado) as erro:
            executar_staging(camada_raw, snapshot_id=SNAPSHOT)
        assert "já está sendo processado" in str(erro.value)
    finally:
        refem.kill()
        refem.wait(timeout=10)


def test_curate_recusa_rodar_com_o_snapshot_travado(camada_raw):
    """A curadoria disputa a **mesma** trava do tratamento, de propósito.

    Não é zelo: a curadoria lê a staging que o tratamento reescreve. Se cada
    etapa tivesse a sua, essa corrida continuaria aberta.
    """
    from cno_pipeline.curate import executar_curadoria
    from cno_pipeline.transform import executar_staging

    executar_staging(camada_raw, snapshot_id=SNAPSHOT)

    sinal = camada_raw.data_dir / "peguei-curate"
    refem = _segurar_em_subprocesso(camada_raw.data_dir, SNAPSHOT, sinal)
    try:
        with pytest.raises(SnapshotOcupado):
            executar_curadoria(camada_raw, snapshot_id=SNAPSHOT)
    finally:
        refem.kill()
        refem.wait(timeout=10)
