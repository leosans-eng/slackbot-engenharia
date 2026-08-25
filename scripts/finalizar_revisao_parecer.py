"""CLI — finaliza revisões de parecer no Idebras com os PDFs da pasta de rede."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from ferramentas.idebras.config import REVISAO_PARECER_DIR
from ferramentas.idebras.revisao_parecer import (
    _gravar_log,
    executar_plano_revisao,
    montar_plano_revisao,
    resultado_do_plano,
)


def _confirmar_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _perguntar_confirmacao(quantidade: int) -> bool:
    if quantidade <= 0:
        return False
    if not sys.stdin.isatty():
        print(
            "Envio cancelado: este comando precisa de confirmação interativa. "
            "Rode no terminal e responda s/N, ou use --simular / --download."
        )
        return False
    print()
    print(
        f"Deseja realmente finalizar {quantidade} parecer(es) no Idebras?"
    )
    print("Isso não pode ser desfeito automaticamente.")
    try:
        resp = input("[s/N] ").strip().lower()
    except EOFError:
        return False
    return resp in {"s", "sim", "y", "yes"}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Mostra o plano de Revisão do Parecer (o que seria finalizado, "
            "o que falta e o que sobra) e, após confirmação, envia os PDFs."
        )
    )
    parser.add_argument(
        "--simular",
        action="store_true",
        help="Só mostra o plano e baixa Words faltantes; não pergunta nem envia.",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Só baixa Words faltantes para a pasta Bot; não finaliza pareceres.",
    )
    parser.add_argument(
        "--finalizar",
        action="store_true",
        help="Não baixa Words; ainda mostra o plano e pede s/N antes de enviar.",
    )
    parser.add_argument(
        "--pasta",
        type=Path,
        default=None,
        help=f"Pasta dos PDFs (padrão: {REVISAO_PARECER_DIR})",
    )
    parser.add_argument(
        "--cpf",
        default=None,
        help="Restringe o plano ao mutuário com este CPF.",
    )
    args = parser.parse_args()

    if args.download and args.finalizar:
        parser.error("Use só uma opção: --download ou --finalizar.")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    _confirmar_stdout()

    baixar = not args.finalizar
    plano = montar_plano_revisao(
        pasta=args.pasta,
        apenas_cpf=args.cpf,
        baixar_word_faltante=baixar,
        on_progress=lambda msg: print(msg),
    )
    operacao = "download" if args.download else "preview"
    preview = resultado_do_plano(plano, simulacao=True, operacao=operacao)
    _gravar_log(plano.pasta, preview)
    print()
    print(preview.texto_log())

    if args.simular or args.download:
        return 1 if preview.falhas or preview.duplicados else 0

    if not plano.pares:
        print("Nenhum parecer seguro para finalizar. Nada foi enviado.")
        return 1 if (preview.falhas or preview.duplicados) else 0

    if not _perguntar_confirmacao(len(plano.pares)):
        cancelado = resultado_do_plano(
            plano, simulacao=True, cancelado=True, operacao="preview"
        )
        _gravar_log(plano.pasta, cancelado)
        print("Envio cancelado. Nenhum parecer foi finalizado.")
        return 0

    resultado = executar_plano_revisao(
        plano,
        on_progress=lambda msg: print(msg),
    )
    print()
    print(resultado.texto_log())
    if resultado.falhas or resultado.duplicados:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
