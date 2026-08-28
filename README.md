# slackbot-engenharia

Bot Slack da Engenharia com ferramentas de automação: formatador SINAPI (i9), fotos de imóveis, perícias finalizadas (Idebras) e fluxos CP (Infobase).

## O que faz

### Bot Slack (`bot/`)

| Comando | Função |
|---------|--------|
| `/i9formatar` | Formata planilhas SINAPI enviadas no canal/DM |
| `/fotos` | Baixa fotos do imóvel no Idebras e envia PDF + ZIP |
| `/parecer` | Baixa o parecer técnico do imóvel no Idebras e envia o PDF |
| `/pericias` | Gera planilha formatada de perícias finalizadas |
| `/revisao` | Plano completo da revisão; responda `sim` para finalizar ou `não` para descartar |
| `/revisao download` | Só baixa Words para a pasta Bot |
| `/revisao finalizar` | Só envia os PDFs no Idebras (sem baixar Word) |
| `/fluxos-cp` | Exporta fluxos do CP (Infobase) e envia a planilha |

O comando `/fluxos-cp` também pode ser enviado automaticamente todo dia em um horário fixo para um canal/usuário — basta configurar `FLUXOS_CP_CANAL` e `FLUXOS_CP_HORARIO`.

O mesmo vale para `/pericias` (data de hoje): `PERICIAS_CANAL` e `PERICIAS_HORARIO` (ex.: `17:40`).

O `/revisao download` também roda sozinho a cada hora, das 08:00 às 17:00, para manter a pasta `Bot` com Words. Só Administradores podem usar os comandos `/revisao`.

### Formatador SINAPI (`ferramentas/formatador_sinapi/`)

Converte planilhas sintéticas do i9 SINAPI em modelos formatados de orçamento:

| Script CLI | Modelo | Descrição |
|------------|--------|-----------|
| `scripts/formatar_modelo1.py` | Modelo 1 (Atualização) | Tabela completa com/sem BDI + Word |
| `scripts/formatar_modelo2.py` | Modelo 2 (Enviar ao Perito) | Layout simplificado com fórmulas Excel |
| `scripts/formatar_modelo3.py` | Modelo 3 (Parecer Inicial) | Apenas c/ BDI + aba Resumo + Word |

### Idebras + CP (`ferramentas/idebras/`)

Automação HTTP do sistema interno Idebras e automação UI do CP Infobase:

- Pesquisa proprietário → galeria → ZIP → PDF
- Pesquisa proprietário → Parecer Técnico → PDF
- Revisão do Parecer → casa PDFs da pasta de rede → Inserir PDF
- Exporta perícias finalizadas por data e formata o Excel
- Login no Infobase → Exportar p/ Excel → formata no padrão

## Requisitos

- Python 3.9+
- [uv](https://github.com/astral-sh/uv) (recomendado) ou `pip`
- Windows com Infobase e Excel instalados (para `/fluxos-cp`)
- Acesso de rede ao servidor Idebras (para `/fotos`, `/parecer`, `/pericias` e `/revisao`)

## Instalação

```bash
uv venv
.venv\Scripts\activate
uv pip install -r requirements.txt
uv pip install -r requirements-bot.txt
uv pip install -e .
```

Ou execute `create_venv.bat` (faz tudo acima automaticamente).

## Bot Slack

```bash
uv run -m bot.app
```

Configure o `.env` a partir de `.env.example` e cadastre os slash commands no painel do Slack — veja [`bot/CONFIGURACAO.md`](bot/CONFIGURACAO.md).

### Exemplos de uso

```
/i9formatar 2
/fotos Maria Souza
/fotos Maria Souza opcao=2
/parecer Maria Souza
/parecer Maria Souza opcao=2
/pericias
/pericias ontem
/pericias 28/07/2026
/revisao
sim
/revisao download
/revisao finalizar
/fluxos-cp
```

## CLI local (formatador)

```bash
python scripts/formatar_modelo1.py
python scripts/formatar_modelo2.py "planilha.xlsx"
python scripts/formatar_modelo3.py --sem-abrir
python scripts/finalizar_revisao_parecer.py --simular
python scripts/finalizar_revisao_parecer.py --download
python scripts/finalizar_revisao_parecer.py --finalizar
python scripts/finalizar_revisao_parecer.py
```

O script de revisão sempre mostra o plano antes. Com `--simular` ele para aí (baixando Words faltantes); `--download` só baixa Words; `--finalizar` não baixa Word e ainda pergunta `s/N` antes de enviar. Sem flag, baixa Words, mostra o plano e pergunta `s/N`.

Opções: `--sem-abrir`, `--sem-word`, `--modelo` (1, 2 ou 3).

## Uso programático

```python
from ferramentas.formatador_sinapi import Modelo, formatar_planilha
from ferramentas.idebras import gerar_relatorio_pericias, gerar_relatorio_fluxos_cp

resultado = formatar_planilha("planilha.xlsx", modelo=Modelo.ATUALIZACAO)
relatorio = gerar_relatorio_pericias()  # hoje
fluxos = gerar_relatorio_fluxos_cp()    # abre Infobase + formata
```

## Estrutura do projeto

```
slackbot-engenharia/
├── bot/                              # Bot Slack
│   ├── app.py                        # Listeners, commands, scheduler
│   ├── handlers.py                   # Lógica de cada comando
│   └── CONFIGURACAO.md
├── ferramentas/
│   ├── formatador_sinapi/            # Formatador SINAPI
│   └── idebras/                      # Fotos, parecer, perícias, fluxos CP
│       ├── fluxo.py
│       ├── fotos.py
│       ├── parecer.py
│       ├── revisao_parecer.py    # Finaliza revisão com PDF da pasta de rede
│       ├── pericias.py
│       ├── fluxos_cp.py
│       ├── fluxos_cp_ui.py           # Automação UI do Infobase
│       └── formatar_fluxos_cp.py
├── scripts/                          # Pontos de entrada CLI
├── modelos/                          # Templates Word e Excel
├── requirements.txt
├── requirements-bot.txt
└── README.md
```

## Variáveis de ambiente

| Variável | Uso |
|----------|-----|
| `SLACK_BOT_TOKEN` | Token do bot (`xoxb-...`) |
| `SLACK_APP_TOKEN` | Socket Mode (`xapp-...`) |
| `LOGIN_USER` / `LOGIN_PASS` | Credenciais Idebras |
| `BASE_URL` | URL do Idebras (padrão `http://andreserver:5050`) |
| `CP_USER` / `CP_PASS` | Credenciais CP Infobase |
| `CP_EXE` | Caminho do `infobase.exe` |
| `FLUXOS_CP_CANAL` | Canal/user ID para envio automático |
| `FLUXOS_CP_HORARIO` | Horário diário `HH:MM` |
| `PERICIAS_CANAL` | Canal/user ID para perícias automáticas |
| `PERICIAS_HORARIO` | Horário diário das perícias `HH:MM` |
| `REVISAO_PARECER_DIR` | Pasta de rede dos PDFs da revisão |
| `REVISAO_USUARIOS` | IDs Slack autorizados a usar `/revisao` |
| `REVISAO_CANAL` | Destinos do download horário de Words |
| `SLACKBOT_TEMP_DIR` | Arquivos temporários do bot |

## Observações

- Planilhas `.xlsx` de entrada/saída ficam fora do Git (`.gitignore`)
- BDI padrão nos totais: **30,62%**
- `/fluxos-cp` requer sessão Windows com desktop (Infobase + Excel)
