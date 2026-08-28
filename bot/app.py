"""
Bot Slack — Socket Mode.
"""

from __future__ import annotations

import logging
import re
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

from bot.config import SlackConfig
from bot.files import resolver_canal_comando
from bot.handlers import (
    executar_comando_fotos,
    executar_comando_formatar,
    executar_comando_parecer,
    executar_comando_pericias,
    executar_fluxos_cp,
    executar_comando_revisao,
    executar_confirmacao_revisao,
    executar_cancelamento_revisao,
    executar_download_revisao_agendado,
    interpretar_modo_revisao,
    registrar_arquivos_da_mensagem,
    texto_parece_cancelamento_revisao,
    texto_parece_confirmacao_revisao,
)
from bot.status_msg import StatusMensagem
from bot.usuarios import (
    MENSAGEM_SEM_PERMISSAO_REVISAO,
    rotulo_usuario,
    usuario_pode_revisao,
)
from ferramentas.idebras.pericias import SemPericiasError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

MENSAGEM_AJUDA = (
    "Olá! Sou o *BOT da Engenharia*. Comandos disponíveis:\n\n"
    "*Formatar planilha SINAPI (i9):*\n"
    "1. Envie a planilha `.xlsx` neste canal ou DM\n"
    "2. Rode o comando:\n"
    "   `/i9formatar modelo=1` — Atualização (+ Word)\n"
    "   `/i9formatar modelo=2` — Enviar ao Perito (Planilha com fórmulas)\n"
    "   `/i9formatar modelo=3` — Parecer Inicial (+ Word)\n\n"
    "*Fotos do imóvel (Idebras):*\n"
    "   `/fotos Nome do Proprietário`\n"
    "   `/fotos Nome do Proprietário opcao=2` — se houver vários imóveis\n"
    "   `/fotos Nome 2` — atalho equivalente\n\n"
    "*Parecer técnico (Idebras):*\n"
    "   `/parecer Nome do Proprietário`\n"
    "   `/parecer Nome do Proprietário opcao=2` — se houver vários imóveis\n"
    "   `/parecer Nome 2` — atalho equivalente\n\n"
    "*Perícias finalizadas (Idebras):*\n"
    "   `/pericias` — data de hoje\n"
    "   `/pericias ontem`\n"
    "   `/pericias 28/07/2026` — data específica\n"
    "*Revisão do parecer (Idebras):*\n"
    "   `/revisao` — plano completo (baixa Words faltantes; responda *sim* ou *não*)\n"
    "   `/revisao download` — só baixa os Words para a pasta Bot\n"
    "   `/revisao finalizar` — só envia os PDFs (sem baixar Word)\n"
    "*Fluxos CP (Infobase):*\n"
    "   `/fluxos-cp` — Gera planilha de fluxos CP"
)

MENSAGEM_NAO_PROGRAMADA = (
    "Recebi sua mensagem: _{texto}_, mas não fui programado para responder a isso ainda. Diga *oi* para receber os comandos disponíveis."
)

MENSAGEM_AGRADECIMENTO = "De nada! Se precisar de algo, é só chamar."


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
        say(
            f"📎 Planilha recebida: *{pendente.nome}*\n"
            f"Agora rode `/i9formatar 1` para Atualização (+ Word), `2` para Enviar ao Perito ou `3` para Parecer Inicial (+ Word)."
        )
    return pendente is not None


def _responder_texto_dm(event, say, client) -> None:
    user_id = event.get("user", "")
    texto = (event.get("text") or "").strip()
    _log_interacao(client, user_id, texto, "message")

    resposta_secreta = _resposta_secreta(texto)
    if resposta_secreta:
        say(resposta_secreta)
        return

    if _texto_parece_agradecimento(texto):
        say(MENSAGEM_AGRADECIMENTO)
        return

    if _texto_parece_saudacao(texto) or not texto:
        say(MENSAGEM_AJUDA)
        return

    say(MENSAGEM_NAO_PROGRAMADA.format(texto=texto))


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
        say(MENSAGEM_SEM_PERMISSAO_REVISAO)
        return True

    if cancelar:
        say(executar_cancelamento_revisao(user_id, channel_id))
        return True

    try:
        canal = resolver_canal_comando(client, channel_id, user_id)
    except ValueError as erro:
        say(f"❌ {erro}")
        return True

    status = StatusMensagem(
        client, canal, "⏳ Finalizando revisões do parecer no Idebras…"
    )
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

        _responder_texto_dm(event, say, client)

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

        status = StatusMensagem(client, canal, "⏳ Buscando fotos no Idebras…")
        try:
            mensagem = executar_comando_fotos(
                client,
                config,
                canal,
                texto,
                user_id=user_id,
                on_progress=status.etapa,
            )
            status.finalizar(mensagem)
        except ValueError as erro:
            status.finalizar(f"❌ {erro}")
        except Exception as erro:
            logger.exception("Falha ao baixar fotos")
            status.finalizar(f"❌ Erro ao baixar fotos: {erro}")

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

        status = StatusMensagem(
            client, canal, "⏳ Buscando parecer técnico no Idebras…"
        )
        try:
            mensagem = executar_comando_parecer(
                client,
                config,
                canal,
                texto,
                user_id=user_id,
                on_progress=status.etapa,
            )
            status.finalizar(mensagem)
        except ValueError as erro:
            status.finalizar(f"❌ {erro}")
        except Exception as erro:
            logger.exception("Falha ao baixar parecer")
            status.finalizar(f"❌ Erro ao baixar parecer: {erro}")

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
        except ValueError as erro:
            status.finalizar(f"❌ {erro}")
        except Exception as erro:
            logger.exception("Falha ao finalizar revisões do parecer")
            status.finalizar(f"❌ Erro ao finalizar revisões: {erro}")

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
                except Exception:
                    logger.exception("Falha no %s agendado", nome)
                    for destino in destinos:
                        try:
                            client.chat_postMessage(
                                channel=destino,
                                text=mensagem_erro,
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

    def _loop() -> None:
        ultima_chave: str | None = None
        while True:
            agora = datetime.now()
            if REVISAO_DOWNLOAD_INICIO <= agora.hour <= REVISAO_DOWNLOAD_FIM:
                chave = agora.strftime("%Y-%m-%d-%H")
                if chave != ultima_chave:
                    ultima_chave = chave
                    logger.info(
                        "Executando download horário da revisão (%s)...", chave
                    )
                    try:
                        executar_download_revisao_agendado(client, destinos)
                        logger.info("Download horário da revisão concluído.")
                    except Exception:
                        logger.exception("Falha no download horário da revisão")
                        for destino in destinos:
                            try:
                                client.chat_postMessage(
                                    channel=destino,
                                    text=(
                                        "❌ Falha no download automático dos "
                                        "Words da revisão. Verifique os logs."
                                    ),
                                )
                            except Exception:
                                pass
            time.sleep(30)

    t = threading.Thread(
        target=_loop,
        daemon=True,
        name="revisao-download-scheduler",
    )
    t.start()


def main() -> None:
    config = SlackConfig.from_env()
    config.validar()
    logger.info("Iniciando bot (Socket Mode)...")
    logger.info(
        "Aguardando eventos. Comandos: /i9formatar, /fotos, /parecer, /pericias, /revisao, /fluxos-cp. "
        "Configuração: bot/CONFIGURACAO.md"
    )

    _iniciar_agendamentos(config)

    app = criar_app()
    handler = SocketModeHandler(app, config.app_token)
    handler.start()


if __name__ == "__main__":
    main()
