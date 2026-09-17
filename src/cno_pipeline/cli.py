"""Interface de linha de comando do pipeline.

O orquestrador (Airflow) chamará estes mesmos comandos, para que qualquer etapa
seja reproduzível na mão exatamente como roda em produção.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from .config import get_settings
from .extract import ErroDeExtracao, ErroDeFonte, HttpSource, carregar_ultimo
from .extract.cno import executar_extracao
from .logging_conf import configurar_logging
from .transform import ErroDeStaging, executar_staging
from .utils import formatar_bytes
from .validate import ErroDeValidacao, executar_validacao

log = logging.getLogger("cno_pipeline.cli")


def _emitir_json(dados: dict) -> None:
    """Imprime o resumo da etapa em JSON, para o orquestrador consumir.

    Vai no stdout enquanto os logs vão no stderr, de modo que a saída possa ser
    lida por um `json.loads` sem filtragem — é assim que a DAG recebe o
    `snapshot_id` de uma etapa e o repassa para a seguinte.
    """
    print(json.dumps(dados, ensure_ascii=False, default=str))


def _cmd_extract(args: argparse.Namespace) -> int:
    settings = get_settings()
    log.info("camada raw em %s", settings.raw_dir)

    resultado = executar_extracao(settings, forcar=args.force)
    m = resultado.manifest

    if args.json:
        _emitir_json(
            {
                "etapa": "extract",
                "snapshot_id": m.snapshot_id,
                "etag": m.etag,
                "reaproveitado": resultado.reaproveitado,
                "sha256_zip": m.sha256_zip,
                "arquivos": [a.nome for a in m.arquivos],
                "totais_controle": m.totais_controle,
            }
        )
        return 0

    print()
    print(f"snapshot        : {m.snapshot_id}")
    print(f"origem          : {m.source_url}")
    print(f"etag            : {m.etag}")
    print(f"publicado em    : {m.last_modified}")
    print(f"pacote          : {formatar_bytes(m.content_length)}")
    print(f"sha256          : {m.sha256_zip}")
    print(f"reaproveitado   : {'sim (nada baixado)' if resultado.reaproveitado else 'não'}")
    print(f"diretório       : {resultado.snapshot_dir}")
    print()
    print("arquivos extraídos:")
    for arquivo in m.arquivos:
        print(f"  {arquivo.nome:22} {formatar_bytes(arquivo.bytes):>10}")
    if m.totais_controle:
        print()
        print("totais de controle publicados pela fonte:")
        for tabela, total in sorted(m.totais_controle.items()):
            print(f"  {tabela:22} {total:>12,}".replace(",", "."))
    return 0


def _cmd_transform(args: argparse.Namespace) -> int:
    settings = get_settings()
    log.info("camada staging em %s", settings.staging_dir)

    resultado = executar_staging(settings, snapshot_id=args.snapshot, forcar=args.force)

    if args.json:
        _emitir_json(
            {
                "etapa": "transform",
                "snapshot_id": resultado.snapshot_id,
                "segundos": round(resultado.segundos_total, 1),
                "tabelas": [
                    {
                        "nome": m.nome,
                        "linhas_origem": m.linhas_origem,
                        "linhas_destino": m.linhas_destino,
                        "duplicatas_removidas": m.duplicatas_removidas,
                    }
                    for m in resultado.tabelas
                ],
            }
        )
        return 0

    print()
    print(f"snapshot        : {resultado.snapshot_id}")
    print(f"tempo total     : {resultado.segundos_total:.1f}s")
    print(f"diretório       : {resultado.staging_dir}")
    print()
    print(f"{'tabela':10} {'origem':>12} {'tratada':>12} {'duplicatas':>12} {'parquet':>10}")
    print("-" * 60)
    for m in resultado.tabelas:
        print(
            f"{m.nome:10} {m.linhas_origem:>12,} {m.linhas_destino:>12,} "
            f"{m.duplicatas_removidas:>12,} {formatar_bytes(m.bytes_parquet):>10}".replace(",", ".")
        )
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    settings = get_settings()
    relatorio = executar_validacao(settings, snapshot_id=args.snapshot)

    if args.json:
        _emitir_json(
            {
                "etapa": "validate",
                "snapshot_id": relatorio.snapshot_id,
                "passou": relatorio.passou,
                "erros": [{"regra": e.nome, "violacoes": e.violacoes} for e in relatorio.erros],
                "avisos": [{"regra": a.nome, "violacoes": a.violacoes} for a in relatorio.avisos],
                "reconciliacao_divergente": [
                    {"tabela": r.tabela, "diferenca": r.diferenca}
                    for r in relatorio.reconciliacoes_divergentes
                ],
            }
        )
        return 0 if relatorio.passou else 1

    print()
    print(f"snapshot        : {relatorio.snapshot_id}")
    print(f"tempo           : {relatorio.segundos:.1f}s")
    print()

    print("RECONCILIAÇÃO COM OS TOTAIS PUBLICADOS PELA RECEITA")
    print(f"  {'tabela':10} {'lidas':>12} {'oficial':>12} {'dif':>8}  {'dedup':>10}  status")
    for r in relatorio.reconciliacoes:
        oficial = f"{r.total_oficial:,}".replace(",", ".") if r.total_oficial else "—"
        status = "OK" if r.confere else "DIVERGE"
        print(
            f"  {r.tabela:10} {r.linhas_origem:>12,} {oficial:>12} "
            f"{r.diferenca:>8,}  {r.duplicatas_removidas:>10,}  {status}".replace(",", ".")
        )

    print()
    print("REGRAS")
    for r in relatorio.regras:
        marca = "ok  " if r.passou else ("ERRO" if r.severidade == "erro" else "aviso")
        n = "" if r.passou else f"{r.violacoes:,}".replace(",", ".")
        print(f"  [{marca:>5}] {r.nome:34} {n:>12}  {r.descricao}")

    problemas = relatorio.erros + relatorio.avisos
    if problemas:
        print()
        print("EXEMPLOS")
        for r in problemas:
            if not r.exemplos:
                continue
            print(f"  {r.nome}:")
            for exemplo in r.exemplos[:3]:
                campos = "  ".join(f"{k}={v}" for k, v in exemplo.items())
                print(f"    {campos}")

    print()
    if relatorio.passou:
        print(f"RESULTADO: aprovado ({len(relatorio.avisos)} avisos)")
        return 0
    print(
        f"RESULTADO: reprovado — {len(relatorio.erros)} regras com erro, "
        f"{len(relatorio.reconciliacoes_divergentes)} divergências de reconciliação"
    )
    return 1


def _cmd_info(args: argparse.Namespace) -> int:
    """Consulta a fonte e o estado local sem baixar nada."""
    settings = get_settings()

    with HttpSource(settings) as fonte:
        info = fonte.inspecionar()

    local = carregar_ultimo(settings.manifests_dir)

    if args.json:
        print(
            json.dumps(
                {
                    "remoto": {
                        "etag": info.etag,
                        "last_modified": info.last_modified,
                        "content_length": info.content_length,
                        "aceita_range": info.aceita_range,
                        "publicado_em": (
                            info.data_publicacao.isoformat() if info.data_publicacao else None
                        ),
                    },
                    "local": local.to_dict() if local else None,
                    "atualizado": bool(local and local.etag == info.etag),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    print("FONTE REMOTA")
    print(f"  publicado em  : {info.data_publicacao}")
    print(f"  etag          : {info.etag}")
    print(f"  tamanho       : {formatar_bytes(info.content_length)}")
    print(f"  aceita range  : {'sim' if info.aceita_range else 'não'}")
    print()
    print("ESTADO LOCAL")
    if not local:
        print("  nenhum snapshot extraído ainda")
        return 0
    print(f"  snapshot      : {local.snapshot_id}")
    print(f"  etag          : {local.etag}")
    print(f"  baixado em    : {local.baixado_em}")
    print()
    if local.etag == info.etag:
        print("=> atualizado: `cno extract` não baixaria nada")
    else:
        print("=> desatualizado: há uma publicação nova na fonte")
    return 0


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cno",
        description="Pipeline de extração e tratamento da base do CNO.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="log em nível DEBUG")
    sub = parser.add_subparsers(dest="comando", required=True)

    p_extract = sub.add_parser("extract", help="baixa e descompacta o snapshot atual na camada raw")
    p_extract.add_argument(
        "--force",
        action="store_true",
        help="rebaixa mesmo que o snapshot local já esteja atualizado",
    )
    p_extract.add_argument("--json", action="store_true", help="resumo em JSON no stdout")
    p_extract.set_defaults(func=_cmd_extract)

    p_transform = sub.add_parser(
        "transform", help="trata a camada raw e materializa parquet em staging"
    )
    p_transform.add_argument(
        "--snapshot",
        help="snapshot a tratar (AAAA-MM-DD). Padrão: o mais recente extraído",
    )
    p_transform.add_argument(
        "--force",
        action="store_true",
        help="refaz a transcodificação intermediária mesmo se estiver válida",
    )
    p_transform.add_argument("--json", action="store_true", help="resumo em JSON no stdout")
    p_transform.set_defaults(func=_cmd_transform)

    p_validate = sub.add_parser(
        "validate", help="valida a camada tratada e reconcilia com os totais oficiais"
    )
    p_validate.add_argument(
        "--snapshot",
        help="snapshot a validar (AAAA-MM-DD). Padrão: o mais recente tratado",
    )
    p_validate.add_argument("--json", action="store_true", help="resumo em JSON no stdout")
    p_validate.set_defaults(func=_cmd_validate)

    p_info = sub.add_parser("info", help="compara a fonte com o estado local, sem baixar nada")
    p_info.add_argument("--json", action="store_true", help="saída em JSON")
    p_info.set_defaults(func=_cmd_info)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    configurar_logging(args.verbose)
    try:
        return args.func(args)
    except (ErroDeFonte, ErroDeExtracao, ErroDeStaging, ErroDeValidacao) as exc:
        # Falhas esperadas viram mensagem limpa e código de saída != 0, para o
        # orquestrador marcar a task como falha sem um traceback inútil.
        log.error("%s", exc)
        return 1
    except KeyboardInterrupt:
        log.warning("interrompido pelo usuário")
        return 130


if __name__ == "__main__":
    sys.exit(main())
