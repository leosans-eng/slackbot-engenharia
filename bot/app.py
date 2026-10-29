"""
Bot Slack — Socket Mode.
"""

from __future__ import annotations

import logging
import re
import socket
import threading
import time
from datetime import datetime

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient

from bot.botoes import (
    ACAO_CONTINUAR,
    ACAO_IMOVEL,
    ACAO_REVISAO_CANCELAR,
    ACAO_REVISAO_FINALIZAR,
    ACAO_TENTAR,
    RespostaComBotoes,
    blocos_modelos,
    blocos_outro_arquivo,
    blocos_revisao,
    blocos_tentar_de_novo,
    ler_valor_acao,
    montar_escolha_imovel,
    ocupar_mensagem,
    postar_botoes,
    substituir_mensagem_botoes,
)
from bot.config import SlackConfig
from bot.isolamento import (
    TIMEOUT_DOWNLOAD_HORARIO,
    rodar_download_horario_em_background,
)
from bot.files import descrever_erro_envio, resolver_canal_comando
from bot.frases import PedidoFrase, interpretar_frase
from bot.handlers import (
    executar_comando_fotos,
    executar_comando_formatar,
    executar_comando_parecer,
    executar_comando_pericias,
    executar_fluxos_cp,
    executar_comando_revisao,
    executar_confirmacao_revisao,
    executar_cancelamento_revisao,
    interpretar_argumentos_imovel,
    interpretar_modo_revisao,
    formatar_busca_imovel,
    registrar_arquivos_da_mensagem,
    texto_parece_cancelamento_revisao,
    texto_parece_confirmacao_revisao,
)
from bot.logging_setup import configurar_logging
from bot.status_msg import StatusMensagem, postar_mensagem
from bot.state import obter_planilha_pendente, obter_revisao_pendente
from bot.usuarios import (
    MENSAGEM_SEM_PERMISSAO_REVISAO,
    rotulo_usuario,
    usuario_pode_revisao,
)
from ferramentas.idebras import listar_resultados_fluxo
from ferramentas.idebras.pericias import SemPericiasError

configurar_logging()
logger = logging.getLogger(__name__)

MENSAGEM_AJUDA = (
    "Olá! Sou o *BOT da Engenharia*. Comandos disponíveis:\n\n"
    "*Formatar planilha SINAPI (i9):*\n"
    "1. Envie a planilha `.xlsx` neste canal ou DM\n"
    "2. Escolha nos botões: *Atualização*, *Perito* ou *Parecer Inicial*\n"
    "   `/i9formatar 1`, `2` ou `3` também funciona.\n\n"
    "*Fotos do imóvel (Idebras):*\n"
    "   `/fotos Nome do Proprietário`\n"
    "   Se houver vários imóveis, escolha no botão de cada um.\n"
    "   O número entre parênteses escolhe direto: `/fotos Maria da Silva 104276`\n\n"
    "*Parecer técnico (Idebras):*\n"
    "   `/parecer Nome do Proprietário`\n"
    "   Se houver vários imóveis, escolha no botão de cada um.\n\n"
    "*Perícias finalizadas (Idebras):*\n"
    "   `/pericias` — data de hoje\n"
    "   `/pericias ontem`\n"
    "   `/pericias 11/09` — dia/mês no ano atual\n"
    "   `/pericias 28/07/2026` — data específica\n"
    "*Revisão do parecer (Idebras):*\n"
    "   `/revisao` — plano completo; depois use *Finalizar* ou *Cancelar*\n"
    "   `/revisao download` — só baixa os Words para a pasta Bot\n"
    "   `/revisao finalizar` — só envia os PDFs (sem baixar Word)\n"
    "*Fluxos CP (Infobase):*\n"
    "   `/fluxos-cp` — Gera planilha de fluxos CP\n\n"
    "Na conversa direta também pode pedir em frase:\n"
    "   `fotos da Maria Souza` ou `fotos e parecer da Maria Souza`\n"
    "   Se houver vários imóveis, um botão baixa fotos e parecer.\n"
    "   `parecer da Maria`\n"
    "   `o que vence hoje` — só o resumo, sem planilha\n"
    "   `teve perícia ontem?` ou `relatório de manifestações`\n"
    "   `baixe as revisões`\n"
)

MENSAGEM_NAO_PROGRAMADA = (
    "Recebi sua mensagem: _{texto}_, mas não entendi. "
    "Diga *oi* para os comandos, ou peça por exemplo *fotos da Maria Souza*, "
    "*teve perícia ontem?* ou *baixe as revisões*."
)

MENSAGEM_AGRADECIMENTO = "De nada! Se precisar de algo, é só chamar."
MENSAGEM_DESISTIR = "Ok 👍"
_DESISTIR = re.compile(
    r"^(?:"
    r"deixa quieto|"
    r"deixa pra l[aá]|"
    r"deixa assim|"
    r"pode deixar|"
    r"esquece(?: isso)?|"
    r"tanto faz|"
    r"n[aã]o precisa(?: mais)?"
    r")$",
    re.IGNORECASE,
)
MENSAGEM_RISADA = "O que é tão engraçado? 🤨"
_RISADA = re.compile(
    r"^(?:"
    r"k{2,}|"
    r"a?(?:ha){2,}h?|"
    r"(?:he){2,}h?|"
    r"(?:hi){2,}h?|"
    r"(?:hue){2,}|"
    r"(?:rs){2,}|"
    r"(?:ks){2,}|"
    r"lol+|"
    r"lmao+"
    r")$",
    re.IGNORECASE,
)
_RISADA_EMOJI = re.compile(r"(?:😂|🤣|😅|😆|😹|:joy:|:rofl:|:laughing:|:sweat_smile:)")


def _texto_parece_saudacao(texto: str) -> bool:
    texto = texto.lower().strip()
    return bool(re.search(r"\b(ol[aá]|oi|hello|hi|ajuda|help|teste|testando|fala|eai|eae|comando|comandos)\b", texto))


def _texto_parece_agradecimento(texto: str) -> bool:
    texto = texto.lower().strip()
    return bool(
        re.search(
            r"\b(brigad[oa]|obrigad[oa]|obrigadoa|valeu|vlw|thanks|thank\s*you|agradecid[oa]|grato|grata)\b",
            texto,
        )
    )


def _texto_parece_desistir(texto: str) -> bool:
    bruto = (texto or "").strip().lower()
    bruto = re.sub(r"[?!.,;:]+", "", bruto)
    bruto = re.sub(r"\s+", " ", bruto).strip()
    return bool(_DESISTIR.fullmatch(bruto))


def _texto_parece_risada(texto: str) -> bool:
    bruto = (texto or "").strip().lower()
    if not bruto:
        return False
    sem_emoji = _RISADA_EMOJI.sub(" ", bruto)
    sem_emoji = re.sub(r"[?!.,;:~\s]+", " ", sem_emoji).strip()
    if not sem_emoji:
        return _RISADA_EMOJI.search(bruto) is not None
    return all(_RISADA.fullmatch(parte) for parte in sem_emoji.split())


def _resposta_secreta(texto: str) -> str | None:
    chave = texto.lower().strip()
    if chave == "ping":
        return "Pong!"
    if chave == "cpj":
        return "Adilsooooon, os meninos já aprenderam o CPJ?"
    return None


def _log_interacao(client, user_id: str, texto: str, origem: str) -> None:
    logger.info(
        "%s — %s — mensagem=%r",
        origem,
        rotulo_usuario(client, user_id),
        texto,
    )


def _tratar_arquivos_na_mensagem(event, client, say=None) -> bool:
    """Registra planilhas anexadas. Retorna True se havia .xlsx."""
    arquivos = event.get("files") or []
    if not arquivos:
        return False

    user_id = event.get("user")
    channel_id = event.get("channel")
    if not user_id or not channel_id:
        return False

    nomes = [a.get("name", "?") for a in arquivos]
    _log_interacao(client, user_id, f"[arquivos: {', '.join(nomes)}]", "message (anexo)")

    pendente = registrar_arquivos_da_mensagem(user_id, channel_id, arquivos, client=client)
    if pendente and say:
        resposta = blocos_modelos(pendente.nome, user_id)
        say(text=resposta.texto, blocks=resposta.blocks)
    return pendente is not None


def _responder_texto_dm(event, say, client, config: SlackConfig) -> None:
    user_id = event.get("user", "")
    texto = (event.get("text") or "").strip()
    _log_interacao(client, user_id, texto, "message")

    resposta_secreta = _resposta_secreta(texto)
    if resposta_secreta:
        say(resposta_secreta)
        return

    pedido = interpretar_frase(texto)
    if pedido:
        _executar_frase_dm(event, client, config, pedido)
        return

    if _texto_parece_agradecimento(texto):
        say(MENSAGEM_AGRADECIMENTO)
        return

    if _texto_parece_saudacao(texto) or not texto:
        say(MENSAGEM_AJUDA)
        return

    if _texto_parece_risada(texto):
        say(MENSAGEM_RISADA)
        return

    if _texto_parece_desistir(texto):
        say(MENSAGEM_DESISTIR)
        return

    say(MENSAGEM_NAO_PROGRAMADA.format(texto=texto))


def _executar_frase_dm(event, client, config: SlackConfig, pedido: PedidoFrase) -> None:
    user_id = event.get("user", "")
    channel_id = event.get("channel", "")
    _log_interacao(
        client,
        user_id,
        f"{pedido.comando} {pedido.argumento}".strip(),
        "frase na DM",
    )
    try:
        canal = resolver_canal_comando(client, channel_id, user_id)
    except ValueError as erro:
        postar_mensagem(client, channel_id, f"❌ {erro}")
        return

    if pedido.comando == "fotos_parecer":
        _baixar_fotos_e_parecer(client, config, user_id, canal, pedido.argumento)
        return

    if pedido.comando in {"fotos", "parecer"}:
        _buscar_imovel_no_slack(
            client,
            config,
            user_id,
            canal,
            pedido.argumento,
            comando=pedido.comando,
        )
        return

    if pedido.comando == "formatar":
        _formatar_por_frase(client, config, user_id, channel_id, canal, pedido.argumento)
        return

    if pedido.comando == "revisao":
        if not usuario_pode_revisao(user_id):
            postar_mensagem(client, canal, MENSAGEM_SEM_PERMISSAO_REVISAO)
            return
        try:
            modo = interpretar_modo_revisao(pedido.argumento)
        except ValueError as erro:
            postar_mensagem(client, canal, f"❌ {erro}")
            return
        _concluir_revisao(client, config, user_id, canal, pedido.argumento, modo)
        return

    if pedido.comando == "prazos":
        _responder_prazos(client, config, user_id, canal, pedido.argumento)
        return

    status = StatusMensagem(
        client, canal, "⏳ Gerando planilha de perícias finalizadas…"
    )
    try:
        mensagem = executar_comando_pericias(
            client,
            config,
            canal,
            pedido.argumento,
            user_id=user_id,
        )
        status.finalizar(mensagem)
    except SemPericiasError as erro:
        status.finalizar(str(erro))
    except ValueError as erro:
        status.finalizar(f"❌ {erro}")
    except Exception as erro:
        logger.exception("Falha ao gerar perícias pela frase na DM")
        status.finalizar(f"❌ Erro ao gerar perícias: {erro}")


def _formatar_por_frase(
    client,
    config: SlackConfig,
    user_id: str,
    channel_id: str,
    canal: str,
    modelo: str,
) -> None:
    pendente_canal = channel_id if obter_planilha_pendente(user_id, channel_id) else canal
    pendente = obter_planilha_pendente(user_id, pendente_canal)
    if pendente is None:
        postar_mensagem(
            client,
            canal,
            "❌ Nenhuma planilha `.xlsx` encontrada.\n"
            "Envie o arquivo nesta conversa e peça de novo, "
            "por exemplo *formata no modelo do perito*.",
        )
        return
    if not modelo:
        postar_botoes(client, canal, blocos_modelos(pendente.nome, user_id))
        return
    try:
        mensagem = executar_comando_formatar(
            client,
            config,
            pendente_canal,
            user_id,
            modelo,
        )
    except ValueError as erro:
        postar_mensagem(client, canal, f"❌ {erro}")
        return
    except Exception as erro:
        logger.exception("Falha ao formatar planilha pela frase na DM")
        postar_mensagem(client, canal, f"❌ Erro ao formatar: {erro}")
        return
    postar_mensagem(client, canal, mensagem)


def _concluir_revisao(
    client,
    config: SlackConfig,
    user_id: str,
    canal: str,
    texto: str,
    modo: str,
) -> None:
    titulos = {
        "preview": "⏳ Conferindo revisões do parecer (prévia, sem finalizar)…",
        "download": "⏳ Baixando Words automáticos para a pasta Bot…",
        "finalizar": "⏳ Finalizando revisões do parecer no Idebras…",
        "confirmar": "⏳ Finalizando revisões do parecer no Idebras…",
        "cancelar": "⏳ Descartando a prévia da revisão…",
    }
    status = StatusMensagem(client, canal, titulos[modo])
    try:
        mensagem = executar_comando_revisao(
            client,
            config,
            canal,
            texto,
            user_id=user_id,
            on_progress=status.etapa,
        )
        status.finalizar(mensagem)
        if modo == "preview" and obter_revisao_pendente(user_id, canal):
            try:
                postar_botoes(client, canal, blocos_revisao(user_id))
            except Exception:
                logger.exception("Falha ao publicar botões da revisão")
                try:
                    postar_mensagem(
                        client,
                        canal,
                        "Não consegui mostrar os botões. "
                        "Responda *sim* para finalizar ou *não* para descartar.",
                    )
                except Exception:
                    logger.exception("Falha ao avisar a alternativa da revisão")
    except ValueError as erro:
        status.finalizar(f"❌ {erro}")
    except Exception as erro:
        logger.exception("Falha ao finalizar revisões do parecer")
        status.finalizar(f"❌ Erro ao finalizar revisões: {erro}")


def _tratar_confirmacao_revisao(event, say, client) -> bool:
    """Se houver prévia pendente, trata sim/confirmar ou não/cancelar."""
    from bot.state import obter_revisao_pendente

    user_id = event.get("user", "")
    channel_id = event.get("channel", "")
    texto = event.get("text") or ""
    if not user_id or not channel_id:
        return False
    confirmar = texto_parece_confirmacao_revisao(texto)
    cancelar = texto_parece_cancelamento_revisao(texto)
    if not confirmar and not cancelar:
        return False
    if not obter_revisao_pendente(user_id, channel_id):
        return False

    _log_interacao(
        client,
        user_id,
        texto,
        "cancelamento /revisao" if cancelar else "confirmação /revisao",
    )

    if not usuario_pode_revisao(user_id):
        _avisar_revisao(client, channel_id, say, MENSAGEM_SEM_PERMISSAO_REVISAO)
        return True

    if cancelar:
        mensagem = executar_cancelamento_revisao(user_id, channel_id)
        _avisar_revisao(client, channel_id, say, mensagem)
        return True

    try:
        canal = resolver_canal_comando(client, channel_id, user_id)
    except ValueError as erro:
        _avisar_revisao(client, channel_id, say, f"❌ {erro}")
        return True

    try:
        status = StatusMensagem(
            client, canal, "⏳ Finalizando revisões do parecer no Idebras…"
        )
    except Exception:
        logger.exception("Falha ao publicar status da revisão no Slack")
        _avisar_revisao(
            client,
            channel_id,
            say,
            "❌ Não consegui enviar a mensagem de status no Slack. "
            "Tente de novo em instantes.",
        )
        return True
    try:
        mensagem = executar_confirmacao_revisao(
            user_id,
            channel_id,
            on_progress=status.etapa,
        )
        status.finalizar(mensagem)
    except ValueError as erro:
        status.finalizar(f"❌ {erro}")
    except Exception as erro:
        logger.exception("Falha ao confirmar revisão do parecer")
        status.finalizar(f"❌ Erro ao finalizar revisões: {erro}")
    return True


def _concluir_status(status: StatusMensagem, mensagem: str | RespostaComBotoes) -> str:
    if isinstance(mensagem, RespostaComBotoes):
        status.finalizar(
            mensagem.texto,
            blocks=mensagem.blocks,
            alternativa=mensagem.alternativa,
        )
        return mensagem.texto
    status.finalizar(mensagem)
    return mensagem


def _dados_do_clique(body: dict) -> tuple[str, str, str, dict]:
    action = (body.get("actions") or [{}])[0]
    user_id = (body.get("user") or {}).get("id") or ""
    channel_id = (body.get("channel") or {}).get("id") or ""
    ts = (body.get("message") or {}).get("ts") or ""
    return user_id, channel_id, ts, ler_valor_acao(action)


def _avisar_ephemeral(client, channel_id: str, user_id: str, texto: str) -> None:
    if not channel_id or not user_id:
        return
    try:
        client.chat_postEphemeral(channel=channel_id, user=user_id, text=texto)
    except Exception:
        logger.exception("Falha ao enviar aviso efêmero")


def _clique_de_outro(client, channel_id: str, user_id: str, dono: str) -> bool:
    if dono and user_id and dono != user_id:
        _avisar_ephemeral(
            client,
            channel_id,
            user_id,
            f"Esses botões são de <@{dono}>.",
        )
        return True
    return False


def _responder_prazos(
    client,
    config: SlackConfig,
    user_id: str,
    canal: str,
    texto: str,
) -> None:
    status = StatusMensagem(client, canal, "⏳ Montando o resumo de prazos…")
    try:
        mensagem = executar_comando_pericias(
            client,
            config,
            canal,
            texto,
            user_id=user_id,
            enviar_planilha=False,
        )
        status.finalizar(mensagem)
    except SemPericiasError as erro:
        status.finalizar(str(erro))
    except ValueError as erro:
        status.finalizar(f"❌ {erro}")
    except Exception as erro:
        logger.exception("Falha ao montar resumo de prazos")
        _concluir_status(
            status,
            blocos_tentar_de_novo(
                f"❌ Erro ao consultar os prazos: {erro}",
                "prazos",
                texto,
                user_id,
            ),
        )


def _baixar_fotos_e_parecer(
    client,
    config: SlackConfig,
    user_id: str,
    canal: str,
    texto: str,
) -> None:
    """Uma pesquisa. Se houver vários imóveis, um botão vale para fotos e parecer."""
    try:
        nome, indice, processo = interpretar_argumentos_imovel(texto, comando="fotos")
    except ValueError as erro:
        postar_mensagem(client, canal, f"❌ {erro}")
        return

    if indice is None:
        status = StatusMensagem(client, canal, "⏳ Buscando imóveis no Idebras…")
        try:
            resultados = listar_resultados_fluxo(nome, processo=processo)
        except ValueError as erro:
            status.finalizar(f"❌ {erro}")
            return
        except Exception as erro:
            logger.exception("Falha ao listar imóveis para fotos e parecer")
            _concluir_status(
                status,
                blocos_tentar_de_novo(
                    f"❌ {erro}",
                    "fotos_parecer",
                    texto,
                    user_id,
                ),
            )
            return
        if not resultados:
            status.finalizar(
                '❌ Nenhum resultado com "Ver Informações". '
                "Confira o nome do proprietário ou se há fluxos baixados."
            )
            return
        if len(resultados) > 1:
            linhas = [
                f'Encontrei *{len(resultados)}* imóveis para "{nome}". '
                "Escolha um. Fotos e parecer saem desse imóvel.",
            ]
            for i, item in enumerate(resultados, start=1):
                preview = item.label if len(item.label) <= 100 else item.label[:97] + "..."
                linhas.append(f"  *[{i}]* {preview}")
            resposta = montar_escolha_imovel(
                "fotos_parecer",
                nome,
                [item.label for item in resultados],
                user_id,
                alternativa="\n".join(linhas),
                processo=processo,
            )
            _concluir_status(status, resposta)
            return
        status.finalizar("Um imóvel encontrado. Baixando fotos e parecer.")

    texto_busca = formatar_busca_imovel(nome, indice, processo)
    _buscar_imovel_no_slack(
        client,
        config,
        user_id,
        canal,
        texto_busca,
        comando="fotos",
        oferecer_outro=False,
    )
    _buscar_imovel_no_slack(
        client,
        config,
        user_id,
        canal,
        texto_busca,
        comando="parecer",
        oferecer_outro=False,
    )


def _buscar_imovel_no_slack(
    client,
    config: SlackConfig,
    user_id: str,
    canal: str,
    texto: str,
    *,
    comando: str,
    oferecer_outro: bool = True,
) -> str:
    if comando == "parecer":
        status = StatusMensagem(
            client, canal, "⏳ Buscando parecer técnico no Idebras…"
        )
        executar = executar_comando_parecer
        rotulo_erro = "parecer"
    else:
        status = StatusMensagem(client, canal, "⏳ Buscando fotos no Idebras…")
        executar = executar_comando_fotos
        rotulo_erro = "fotos"
    try:
        mensagem = executar(
            client,
            config,
            canal,
            texto,
            user_id=user_id,
            on_progress=status.etapa,
        )
        if oferecer_outro and isinstance(mensagem, str):
            mensagem = _com_botao_do_outro(mensagem, comando, texto, user_id)
        texto_resposta = _concluir_status(status, mensagem)
        logger.info(
            "comando /%s concluído — usuário=%s — texto=%r — resposta=%r",
            comando,
            rotulo_usuario(client, user_id),
            texto,
            texto_resposta,
        )
        return texto_resposta
    except ValueError as erro:
        status.finalizar(f"❌ {erro}")
        logger.warning(
            "comando /%s recusado — usuário=%s — texto=%r — erro=%s",
            comando,
            rotulo_usuario(client, user_id),
            texto,
            erro,
        )
        return ""
    except Exception as erro:
        logger.exception("Falha ao baixar %s", rotulo_erro)
        _concluir_status(
            status,
            blocos_tentar_de_novo(
                f"❌ Erro ao baixar {rotulo_erro}: {erro}",
                comando,
                texto,
                user_id,
            ),
        )
        return ""


def _com_botao_do_outro(
    mensagem: str,
    comando: str,
    texto: str,
    user_id: str,
) -> str | RespostaComBotoes:
    if comando not in {"fotos", "parecer"}:
        return mensagem
    try:
        nome, indice, processo = interpretar_argumentos_imovel(texto, comando=comando)
    except ValueError:
        return mensagem
    return blocos_outro_arquivo(
        mensagem,
        comando,
        nome,
        user_id,
        indice=indice,
        processo=processo,
    )


def _texto_do_botao_imovel(dados: dict) -> str:
    nome = str(dados.get("n") or "").strip()
    processo = str(dados.get("p") or "").strip()
    try:
        indice = int(dados.get("i") or 0)
    except (TypeError, ValueError):
        indice = 0
    return formatar_busca_imovel(nome, indice or None, processo or None)


def _tratar_escolha_imovel(config: SlackConfig, body: dict, client) -> None:
    user_id, channel_id, ts, dados = _dados_do_clique(body)
    comando = dados.get("c")
    nome = str(dados.get("n") or "").strip()
    dono = str(dados.get("u") or "")
    try:
        indice = int(dados.get("i"))
    except (TypeError, ValueError):
        indice = 0
    if comando not in {"fotos", "parecer", "fotos_parecer"} or not nome or indice < 1:
        _avisar_ephemeral(client, channel_id, user_id, "Não consegui ler essa escolha.")
        return
    if _clique_de_outro(client, channel_id, user_id, dono):
        return
    if not ocupar_mensagem(ts):
        _avisar_ephemeral(client, channel_id, user_id, "Essa escolha já está em andamento.")
        return
    _log_interacao(client, user_id, f"{comando} {nome} opcao={indice}", "botão imóvel")
    aviso = (
        f"Opção *{indice}* de *{nome}*. Baixando fotos e parecer."
        if comando == "fotos_parecer"
        else f"Opção *{indice}* de *{nome}*."
    )
    try:
        substituir_mensagem_botoes(client, channel_id, ts, aviso)
    except Exception:
        logger.exception("Falha ao tirar os botões da escolha de imóvel")
    texto = _texto_do_botao_imovel(dados)
    if comando == "fotos_parecer":
        _baixar_fotos_e_parecer(
            client, config, dono or user_id, channel_id, texto
        )
        return
    _buscar_imovel_no_slack(
        client,
        config,
        dono or user_id,
        channel_id,
        texto,
        comando=comando,
    )


def _tratar_continuar_imovel(config: SlackConfig, body: dict, client) -> None:
    user_id, channel_id, ts, dados = _dados_do_clique(body)
    comando = dados.get("c")
    nome = str(dados.get("n") or "").strip()
    dono = str(dados.get("u") or "")
    if comando not in {"fotos", "parecer"} or not nome:
        _avisar_ephemeral(client, channel_id, user_id, "Não consegui ler essa escolha.")
        return
    if _clique_de_outro(client, channel_id, user_id, dono):
        return
    if not ocupar_mensagem(ts):
        _avisar_ephemeral(client, channel_id, user_id, "Esse download já está em andamento.")
        return
    texto = _texto_do_botao_imovel(dados)
    rotulo = "parecer" if comando == "parecer" else "fotos"
    _log_interacao(client, user_id, texto, "botão outro arquivo")
    try:
        substituir_mensagem_botoes(
            client,
            channel_id,
            ts,
            f"Baixando {rotulo} de *{nome}*.",
        )
    except Exception:
        logger.exception("Falha ao tirar o botão do outro arquivo")
    _buscar_imovel_no_slack(
        client,
        config,
        dono or user_id,
        channel_id,
        texto,
        comando=comando,
    )


def _tratar_tentar_de_novo(config: SlackConfig, body: dict, client) -> None:
    user_id, channel_id, ts, dados = _dados_do_clique(body)
    comando = str(dados.get("c") or "")
    texto = str(dados.get("t") or "")
    dono = str(dados.get("u") or "")
    if comando not in {"fotos", "parecer", "fotos_parecer", "prazos"}:
        _avisar_ephemeral(client, channel_id, user_id, "Não consegui repetir esse pedido.")
        return
    if _clique_de_outro(client, channel_id, user_id, dono):
        return
    if not ocupar_mensagem(ts):
        _avisar_ephemeral(client, channel_id, user_id, "Essa tentativa já está em andamento.")
        return
    _log_interacao(client, user_id, f"{comando} {texto}".strip(), "botão tentar de novo")
    try:
        substituir_mensagem_botoes(client, channel_id, ts, "Tentando de novo…")
    except Exception:
        logger.exception("Falha ao tirar o botão de tentar de novo")
    dono_id = dono or user_id
    if comando == "fotos_parecer":
        _baixar_fotos_e_parecer(client, config, dono_id, channel_id, texto)
        return
    if comando == "prazos":
        _responder_prazos(client, config, dono_id, channel_id, texto)
        return
    _buscar_imovel_no_slack(
        client,
        config,
        dono_id,
        channel_id,
        texto,
        comando=comando,
    )


def _tratar_modelo(config: SlackConfig, body: dict, client) -> None:
    user_id, channel_id, ts, dados = _dados_do_clique(body)
    dono = str(dados.get("u") or "")
    try:
        modelo = int(dados.get("m"))
    except (TypeError, ValueError):
        modelo = 0
    if modelo not in {1, 2, 3}:
        _avisar_ephemeral(client, channel_id, user_id, "Modelo inválido.")
        return
    if _clique_de_outro(client, channel_id, user_id, dono):
        return
    if not ocupar_mensagem(ts):
        _avisar_ephemeral(client, channel_id, user_id, "Essa planilha já está sendo formatada.")
        return
    rotulos = {1: "Atualização", 2: "Perito", 3: "Parecer Inicial"}
    _log_interacao(client, user_id, str(modelo), "botão /i9formatar")
    try:
        substituir_mensagem_botoes(
            client,
            channel_id,
            ts,
            f"⏳ Formatando *{rotulos[modelo]}*…",
        )
    except Exception:
        logger.exception("Falha ao tirar os botões do modelo")
    try:
        mensagem = executar_comando_formatar(
            client,
            config,
            channel_id,
            dono or user_id,
            str(modelo),
        )
    except ValueError as erro:
        mensagem = f"❌ {erro}"
    except Exception as erro:
        logger.exception("Falha ao formatar planilha pelo botão")
        mensagem = f"❌ Erro ao formatar: {erro}"
    try:
        substituir_mensagem_botoes(client, channel_id, ts, mensagem)
    except Exception:
        logger.exception("Falha ao publicar o resultado da formatação")
        try:
            postar_mensagem(client, channel_id, mensagem)
        except Exception:
            logger.exception("Falha ao enviar o resultado da formatação")


def _tratar_revisao_botao(body: dict, client, *, finalizar: bool) -> None:
    user_id, channel_id, ts, dados = _dados_do_clique(body)
    dono = str(dados.get("u") or "")
    if _clique_de_outro(client, channel_id, user_id, dono):
        return
    if not usuario_pode_revisao(user_id):
        _avisar_ephemeral(client, channel_id, user_id, MENSAGEM_SEM_PERMISSAO_REVISAO)
        return
    if not ocupar_mensagem(ts):
        _avisar_ephemeral(client, channel_id, user_id, "Essa prévia já está sendo processada.")
        return
    autor = dono or user_id
    _log_interacao(
        client,
        user_id,
        "finalizar" if finalizar else "cancelar",
        "botão /revisao",
    )
    if not finalizar:
        mensagem = executar_cancelamento_revisao(autor, channel_id)
        try:
            substituir_mensagem_botoes(client, channel_id, ts, mensagem)
        except Exception:
            logger.exception("Falha ao confirmar o cancelamento da revisão")
        return

    try:
        substituir_mensagem_botoes(client, channel_id, ts, "⏳ Finalizando a prévia…")
    except Exception:
        logger.exception("Falha ao tirar os botões da revisão")
    try:
        status = StatusMensagem(
            client, channel_id, "⏳ Finalizando revisões do parecer no Idebras…"
        )
    except Exception:
        logger.exception("Falha ao publicar status da revisão")
        return
    try:
        mensagem = executar_confirmacao_revisao(
            autor,
            channel_id,
            on_progress=status.etapa,
        )
        status.finalizar(mensagem)
    except ValueError as erro:
        status.finalizar(f"❌ {erro}")
    except Exception as erro:
        logger.exception("Falha ao confirmar revisão pelo botão")
        status.finalizar(f"❌ Erro ao finalizar revisões: {erro}")


def _avisar_revisao(client, channel_id: str, say, texto: str) -> None:
    """Confirma cancelamento/erros no Slack mesmo com DNS instável."""
    try:
        postar_mensagem(client, channel_id, texto)
        return
    except Exception:
        logger.exception("chat.postMessage com retry falhou; tentando say() do Bolt")
    try:
        say(texto)
    except Exception:
        logger.exception(
            "Não foi possível avisar no Slack (a ação local já pode ter ocorrido): %s",
            texto,
        )


def criar_app() -> App:
    config = SlackConfig.from_env()
    config.validar()
    app = App(token=config.bot_token)

    @app.middleware
    def registrar_eventos(body, next):
        tipo = body.get("type")
        if tipo in ("events_api", "event_callback"):
            evento = body.get("event", {})
            logger.info("Evento recebido: %s", evento.get("type", "?"))
        elif tipo:
            logger.info("Payload recebido: %s", tipo)
        next()

    @app.error
    def tratar_erro(error, body, logger):
        logger.exception("Erro no handler Slack: %s", error)

    @app.event("message")
    def ao_receber_mensagem(event, say, client):
        if event.get("bot_id"):
            return

        subtype = event.get("subtype")
        if subtype and subtype not in ("file_share", "file_comment"):
            return

        if _tratar_arquivos_na_mensagem(event, client, say=say):
            return

        if _tratar_confirmacao_revisao(event, say, client):
            return

        channel_type = event.get("channel_type")
        if channel_type and channel_type != "im":
            return

        _responder_texto_dm(event, say, client, config)

    @app.event("app_mention")
    def mencao(event, say, client):
        user_id = event.get("user", "")
        texto = event.get("text", "")
        texto_limpo = re.sub(r"<@[^>]+>", "", texto).strip()
        _log_interacao(client, user_id, texto_limpo, "app_mention")

        if _tratar_arquivos_na_mensagem(event, client, say=say):
            return

        if _tratar_confirmacao_revisao(event, say, client):
            return

        resposta_secreta = _resposta_secreta(texto_limpo)
        if resposta_secreta:
            say(resposta_secreta)
            return

        if _texto_parece_agradecimento(texto_limpo):
            say(MENSAGEM_AGRADECIMENTO)
            return

        if not texto_limpo or _texto_parece_saudacao(texto_limpo):
            say(MENSAGEM_AJUDA)
        else:
            say(
                f"Recebi: _{texto_limpo}_\n\n"
                "Diga *oi* para ver os comandos (`/i9formatar`, `/fotos`, `/parecer`, `/pericias`, `/revisao`, `/fluxos-cp`)."
            )

    @app.command("/i9formatar")
    def comando_formatar(ack, command, respond, client, logger):
        ack()
        user_id = command.get("user_id", "")
        channel_id = command.get("channel_id", "")
        texto = (command.get("text") or "").strip()
        _log_interacao(client, user_id, texto, "comando /i9formatar")

        if not texto:
            pendente = obter_planilha_pendente(user_id, channel_id)
            if pendente is None:
                respond(
                    "❌ Nenhuma planilha `.xlsx` encontrada.\n"
                    "Envie o arquivo neste canal ou DM e escolha o modelo nos botões."
                )
                return
            try:
                postar_botoes(
                    client,
                    channel_id,
                    blocos_modelos(pendente.nome, user_id),
                )
            except Exception as erro:
                logger.exception("Falha ao publicar botões do modelo")
                respond(f"❌ Não consegui mostrar os botões: {erro}")
                return
            respond("Escolha o modelo nos botões.")
            return

        respond("⏳ Processando planilha…")

        try:
            mensagem = executar_comando_formatar(
                client,
                config,
                channel_id,
                user_id,
                texto,
            )
            respond(mensagem)
        except ValueError as erro:
            respond(f"❌ {erro}")
        except Exception as erro:
            logger.exception("Falha ao formatar planilha")
            respond(f"❌ Erro ao formatar: {erro}")

    @app.command("/fotos")
    def comando_fotos(ack, command, respond, client, logger):
        ack()
        user_id = command.get("user_id", "")
        channel_id = command.get("channel_id", "")
        texto = (command.get("text") or "").strip()
        _log_interacao(client, user_id, texto, "comando /fotos")

        try:
            canal = resolver_canal_comando(client, channel_id, user_id)
        except ValueError as erro:
            respond(f"❌ {erro}")
            return

        _buscar_imovel_no_slack(
            client, config, user_id, canal, texto, comando="fotos"
        )

    @app.command("/parecer")
    def comando_parecer(ack, command, respond, client, logger):
        ack()
        user_id = command.get("user_id", "")
        channel_id = command.get("channel_id", "")
        texto = (command.get("text") or "").strip()
        _log_interacao(client, user_id, texto, "comando /parecer")

        try:
            canal = resolver_canal_comando(client, channel_id, user_id)
        except ValueError as erro:
            respond(f"❌ {erro}")
            return

        _buscar_imovel_no_slack(
            client, config, user_id, canal, texto, comando="parecer"
        )

    @app.command("/pericias")
    def comando_pericias(ack, command, respond, client, logger):
        ack()
        user_id = command.get("user_id", "")
        channel_id = command.get("channel_id", "")
        texto = (command.get("text") or "").strip()
        _log_interacao(client, user_id, texto, "comando /pericias")

        respond("⏳ Gerando planilha de perícias finalizadas…")

        try:
            mensagem = executar_comando_pericias(
                client, config, channel_id, texto, user_id=user_id
            )
            respond(mensagem)
        except SemPericiasError as erro:
            respond(str(erro))
        except ValueError as erro:
            respond(f"❌ {erro}")
        except Exception as erro:
            logger.exception("Falha ao gerar perícias")
            respond(f"❌ Erro ao gerar perícias: {erro}")

    @app.command("/fluxos-cp")
    def comando_fluxos_cp(ack, command, respond, client, logger):
        ack()
        user_id = command.get("user_id", "")
        channel_id = command.get("channel_id", "")
        _log_interacao(client, user_id, "", "comando /fluxos-cp")

        respond("⏳ Abrindo CP e exportando fluxos…")

        try:
            mensagem = executar_fluxos_cp(
                client, config, channel_id, user_id=user_id
            )
            respond(mensagem)
        except ValueError as erro:
            respond(f"❌ {erro}")
        except Exception as erro:
            logger.exception("Falha ao gerar fluxos CP")
            respond(f"❌ Erro ao gerar fluxos CP: {erro}")

    @app.command("/revisao")
    def comando_revisao(ack, command, respond, client, logger):
        ack()
        user_id = command.get("user_id", "")
        channel_id = command.get("channel_id", "")
        texto = (command.get("text") or "").strip()
        _log_interacao(client, user_id, texto, "comando /revisao")

        if not usuario_pode_revisao(user_id):
            respond(MENSAGEM_SEM_PERMISSAO_REVISAO)
            return

        try:
            modo = interpretar_modo_revisao(texto)
        except ValueError as erro:
            respond(f"❌ {erro}")
            return

        try:
            canal = resolver_canal_comando(client, channel_id, user_id)
        except ValueError as erro:
            respond(f"❌ {erro}")
            return

        _concluir_revisao(client, config, user_id, canal, texto, modo)

    @app.action(ACAO_IMOVEL)
    def acao_imovel(ack, body, client):
        ack()
        _tratar_escolha_imovel(config, body, client)

    @app.action(ACAO_CONTINUAR)
    def acao_continuar(ack, body, client):
        ack()
        _tratar_continuar_imovel(config, body, client)

    @app.action(ACAO_TENTAR)
    def acao_tentar(ack, body, client):
        ack()
        _tratar_tentar_de_novo(config, body, client)

    @app.action(ACAO_REVISAO_FINALIZAR)
    def acao_revisao_finalizar(ack, body, client):
        ack()
        _tratar_revisao_botao(body, client, finalizar=True)

    @app.action(ACAO_REVISAO_CANCELAR)
    def acao_revisao_cancelar(ack, body, client):
        ack()
        _tratar_revisao_botao(body, client, finalizar=False)

    @app.action(re.compile(r"^formatar_modelo_[123]$"))
    def acao_modelo(ack, body, client):
        ack()
        _tratar_modelo(config, body, client)

    return app


def _iniciar_agendamento_diario(
    *,
    nome: str,
    canal: str,
    horario: str,
    config: SlackConfig,
    executar,
    mensagem_erro: str,
) -> None:
    """Thread daemon que executa uma tarefa diariamente no horário configurado."""
    from ferramentas.idebras.config import parse_destinos_slack

    destinos = parse_destinos_slack(canal)
    if not destinos or not horario:
        logger.info(
            "Agendamento de %s desativado (canal=%r, horario=%r).",
            nome,
            canal,
            horario,
        )
        return

    try:
        hora, minuto = (int(p) for p in horario.split(":"))
    except (ValueError, TypeError):
        logger.error("Horário inválido para %s: %r. Use HH:MM.", nome, horario)
        return

    logger.info(
        "%s agendado: destinos=%s, horário=%02d:%02d diário.",
        nome,
        destinos,
        hora,
        minuto,
    )

    client = WebClient(token=config.bot_token)

    def _loop() -> None:
        executado_hoje: str | None = None
        while True:
            agora = datetime.now()
            hoje_str = agora.strftime("%Y-%m-%d")

            if (
                agora.hour == hora
                and agora.minute == minuto
                and executado_hoje != hoje_str
            ):
                executado_hoje = hoje_str
                logger.info("Executando %s agendado (%s)...", nome, hoje_str)
                try:
                    # canal original (pode ter vários IDs separados por vírgula)
                    executar(client, config, canal)
                    logger.info("%s agendado concluído.", nome)
                except SemPericiasError as erro:
                    logger.info("%s agendado: %s — envio omitido.", nome, erro)
                except Exception as erro:
                    logger.exception("Falha no %s agendado", nome)
                    texto = (
                        f"{mensagem_erro}\n\n{descrever_erro_envio(erro)}"
                    )
                    for destino in destinos:
                        try:
                            client.chat_postMessage(
                                channel=destino,
                                text=texto,
                            )
                        except Exception:
                            pass

            time.sleep(30)

    t = threading.Thread(
        target=_loop,
        daemon=True,
        name=f"{nome.lower().replace(' ', '-')}-scheduler",
    )
    t.start()


def _iniciar_agendamentos(config: SlackConfig) -> None:
    from ferramentas.idebras.config import (
        FLUXOS_CP_CANAL,
        FLUXOS_CP_HORARIO,
        PERICIAS_CANAL,
        PERICIAS_HORARIO,
    )

    _iniciar_agendamento_diario(
        nome="Fluxos CP",
        canal=FLUXOS_CP_CANAL,
        horario=FLUXOS_CP_HORARIO,
        config=config,
        executar=lambda client, cfg, canal: executar_fluxos_cp(client, cfg, canal),
        mensagem_erro="❌ Falha no envio automático de fluxos CP. Verifique os logs.",
    )

    _iniciar_agendamento_diario(
        nome="Perícias",
        canal=PERICIAS_CANAL,
        horario=PERICIAS_HORARIO,
        config=config,
        executar=lambda client, cfg, canal: executar_comando_pericias(
            client, cfg, canal, "hoje"
        ),
        mensagem_erro="❌ Falha no envio automático de perícias finalizadas. Verifique os logs.",
    )
    _iniciar_agendamento_revisao_download(config)


def _iniciar_agendamento_revisao_download(config: SlackConfig) -> None:
    from ferramentas.idebras.config import (
        REVISAO_CANAL,
        REVISAO_DOWNLOAD_FIM,
        REVISAO_DOWNLOAD_INICIO,
        parse_destinos_slack,
    )

    destinos = parse_destinos_slack(REVISAO_CANAL)
    logger.info(
        "Download horário da revisão: destinos=%s, a cada hora das %02d:00 às %02d:00.",
        destinos,
        REVISAO_DOWNLOAD_INICIO,
        REVISAO_DOWNLOAD_FIM,
    )
    client = WebClient(token=config.bot_token)

    def _avisar(texto: str) -> None:
        for destino in destinos:
            try:
                client.chat_postMessage(channel=destino, text=texto)
            except Exception:
                pass

    def _loop() -> None:
        ultima_chave: str | None = None
        aviso_adiamento: str | None = None
        job_thread: threading.Thread | None = None
        while True:
            agora = datetime.now()
            if REVISAO_DOWNLOAD_INICIO <= agora.hour <= REVISAO_DOWNLOAD_FIM:
                chave = agora.strftime("%Y-%m-%d-%H")
                job_vivo = job_thread is not None and job_thread.is_alive()
                if chave != ultima_chave and not job_vivo:
                    ultima_chave = chave
                    logger.info(
                        "Executando download horário da revisão (%s)...", chave
                    )
                    # Thread dedicada: o scheduler nunca fica preso no wait do
                    # subprocess (e o Socket Mode segue respondendo no Slack).
                    job_thread = rodar_download_horario_em_background(
                        config.bot_token,
                        destinos,
                        timeout=TIMEOUT_DOWNLOAD_HORARIO,
                        on_timeout=lambda erro: _avisar(
                            "❌ O download automático da revisão travou "
                            "(pasta de rede ou Idebras sem resposta) e foi "
                            "encerrado para o bot continuar no Slack.\n\n"
                            f"{descrever_erro_envio(erro)}"
                        ),
                        on_erro=lambda erro: _avisar(
                            "❌ Falha no download automático dos Words da revisão.\n\n"
                            f"{descrever_erro_envio(erro)}"
                        ),
                        on_ok=lambda: logger.info(
                            "Download horário da revisão concluído."
                        ),
                    )
                elif chave != ultima_chave and job_vivo:
                    if aviso_adiamento != chave:
                        logger.warning(
                            "Download horário (%s) adiado: job anterior ainda "
                            "em execução (tenta de novo em breve).",
                            chave,
                        )
                        aviso_adiamento = chave
            time.sleep(30)

    t = threading.Thread(
        target=_loop,
        daemon=True,
        name="revisao-download-scheduler",
    )
    t.start()


def _iniciar_watchdog_socket(handler: SocketModeHandler) -> None:
    """Reconecta o Socket Mode se a sessão cair e a lib não se recuperar."""

    def _loop() -> None:
        while True:
            time.sleep(20)
            try:
                conectado = handler.client.is_connected()
            except Exception:
                conectado = False
            if conectado:
                continue
            logger.warning(
                "Socket Mode desconectado. Forçando reconexão..."
            )
            try:
                handler.client.connect_to_new_endpoint(force=True)
            except Exception:
                logger.exception("Falha ao reconectar o Socket Mode")

    t = threading.Thread(
        target=_loop,
        daemon=True,
        name="socket-mode-watchdog",
    )
    t.start()


def main() -> None:
    # Evita handshake SSL/HTTP eterno se a rede cair (pico de energia, etc.).
    socket.setdefaulttimeout(30)

    config = SlackConfig.from_env()
    config.validar()
    logger.info("Iniciando bot (Socket Mode)...")
    logger.info(
        "Aguardando eventos. Comandos: /i9formatar, /fotos, /parecer, /pericias, /revisao, /fluxos-cp. "
        "Configuração: bot/CONFIGURACAO.md"
    )

    _iniciar_agendamentos(config)

    app = criar_app()
    handler = SocketModeHandler(app, config.app_token, ping_interval=10)
    _iniciar_watchdog_socket(handler)
    handler.start()


if __name__ == "__main__":
    main()
