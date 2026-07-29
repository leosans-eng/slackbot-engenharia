# slackbot-engenharia

Bot Slack da Engenharia com ferramentas de automação: formatador SINAPI (i9), fotos de imóveis e perícias finalizadas (Idebras).

## O que faz

### Bot Slack (`bot/`)

| Comando | Função |
|---------|--------|
| `/i9formatar` | Formata planilhas SINAPI enviadas no canal/DM |
| `/fotos` | Baixa fotos do imóvel no Idebras e envia PDF + ZIP |
| `/pericias` | Gera planilha formatada de perícias finalizadas |

### Formatador SINAPI (`ferramentas/formatador_sinapi/`)

Converte planilhas sintéticas do i9 SINAPI em modelos formatados de orçamento:

| Script CLI | Modelo | Descrição |
|------------|--------|-----------|
| `scripts/formatar_modelo1.py` | Modelo 1 (Atualização) | Tabela completa com/sem BDI + Word |
| `scripts/formatar_modelo2.py` | Modelo 2 (Enviar ao Perito) | Layout simplificado com fórmulas Excel |
| `scripts/formatar_modelo3.py` | Modelo 3 (Parecer Inicial) | Apenas c/ BDI + aba Resumo + Word |

### Idebras (`ferramentas/idebras/`)

Automação HTTP do sistema interno Idebras:

- Pesquisa proprietário → galeria → ZIP → PDF
- Exporta perícias finalizadas por data e formata o Excel

## Requisitos

- Python 3.9+
- [uv](https://github.com/astral-sh/uv) (recomendado) ou `pip`
- Acesso de rede ao servidor Idebras (para `/fotos` e `/pericias`)

## Instalação

```bash
uv venv
.venv\Scripts\activate
uv pip install -r requirements.txt
uv pip install -r requirements-bot.txt
uv pip install -e .
```

Ou execute `create_venv.bat` (faz tudo acima automaticamente).

> O `pip install -e .` registra os pacotes `bot` e `ferramentas` no ambiente.

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
/pericias
/pericias ontem
/pericias 28/07/2026
```

## CLI local (formatador)

```bash
python scripts/formatar_modelo1.py
python scripts/formatar_modelo2.py "planilha.xlsx"
python scripts/formatar_modelo3.py --sem-abrir
```

Opções: `--sem-abrir`, `--sem-word`, `--modelo` (1, 2 ou 3).

## Uso programático

```python
from ferramentas.formatador_sinapi import Modelo, formatar_planilha
from ferramentas.idebras import gerar_relatorio_pericias, download_owner_photos, zip_to_pdf
from pathlib import Path

resultado = formatar_planilha("planilha.xlsx", modelo=Modelo.ATUALIZACAO)
relatorio = gerar_relatorio_pericias()  # hoje
```

## Estrutura do projeto

```
slackbot-engenharia/
├── bot/                              # Bot Slack
│   ├── app.py
│   ├── handlers.py
│   └── CONFIGURACAO.md
├── ferramentas/
│   ├── formatador_sinapi/            # Formatador SINAPI
│   └── idebras/                      # Fotos + perícias (Idebras)
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
| `SLACKBOT_TEMP_DIR` | Arquivos temporários do bot |

## Observações

- Planilhas `.xlsx` de entrada/saída ficam fora do Git (`.gitignore`)
- BDI padrão nos totais: **30,62%**
- Ideal para planilhas do [i9 Orçamentos](https://www.i9orcamentos.com.br/sistema/orcamentos)
