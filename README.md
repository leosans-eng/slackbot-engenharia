# slackbot-engenharia

Bot Slack da Engenharia com ferramentas de automação. A primeira ferramenta disponível é o **formatador de planilhas SINAPI** (exportadas do i9).

## O que faz

### Bot Slack (`bot/`)

- Comando `/i9formatar` para formatar planilhas enviadas no canal ou DM
- Respostas a menções e mensagens diretas

### Formatador SINAPI (`ferramentas/formatador_sinapi/`)

Converte planilhas sintéticas do i9 SINAPI em modelos formatados de orçamento:

| Script CLI | Modelo | Descrição |
|------------|--------|-----------|
| `scripts/formatar_modelo1.py` | Modelo 1 (Atualização) | Tabela completa com/sem BDI + Word |
| `scripts/formatar_modelo2.py` | Modelo 2 (Enviar ao Perito) | Layout simplificado com fórmulas Excel |
| `scripts/formatar_modelo3.py` | Modelo 3 (Parecer Inicial) | Apenas c/ BDI + aba Resumo + Word |

## Requisitos

- Python 3.8+
- [uv](https://github.com/astral-sh/uv) (recomendado) ou `pip`
- Windows recomendado para uso CLI de alguns Scripts (abre Excel ao final), mas roda em Linux e Mac também

## Instalação

```bash
uv venv
.venv\Scripts\activate
uv pip install -r requirements.txt
uv pip install -r requirements-bot.txt
uv pip install -e .
```

Ou execute `create_venv.bat` (faz tudo acima automaticamente).

> O `pip install -e .` registra os pacotes `bot` e `ferramentas` no ambiente. Os scripts em `scripts/` também funcionam sem isso, mas o modo editável é recomendado.

## Bot Slack

```bash
uv run -m bot.app
```

**Uso:** envie um `.xlsx` → `/i9formatar modelo=1` (ou `2`, `3`).

Configuração do app no Slack: [`bot/CONFIGURACAO.md`](bot/CONFIGURACAO.md).

## CLI local (formatador)

```bash
python scripts/formatar_modelo1.py
python scripts/formatar_modelo2.py "planilha.xlsx"
python scripts/formatar_modelo3.py --sem-abrir
```

Opções: `--sem-abrir`, `--sem-word`, `--modelo` (1, 2 ou 3).

### Entrada da planilha (CLI)

1. Argumento na linha de comando
2. `SLACKBOT_ARQUIVO_ENTRADA` (ou legado `FORMATADOR_ARQUIVO_ENTRADA`)
3. `local_config.py` (ARQUIVO_ENTRADA = "NOME DO ARQUIVO .XLSX")
4. Detecção automática de `Planilha Sintética*.xlsx` na pasta

## Uso programático

```python
from ferramentas.formatador_sinapi import Modelo, formatar_planilha

resultado = formatar_planilha("planilha.xlsx", modelo=Modelo.ATUALIZACAO)
print(resultado.caminho_excel)
```

## Estrutura do projeto

```
slackbot-engenharia/
├── bot/                              # Bot Slack
│   ├── app.py
│   ├── handlers.py
│   └── CONFIGURACAO.md
├── ferramentas/
│   └── formatador_sinapi/            # Formatador SINAPI
│       ├── service.py
│       ├── word_modelo1.py
│       └── word_modelo3.py
├── scripts/                          # Pontos de entrada CLI
│   ├── formatar_modelo1.py
│   ├── formatar_modelo2.py
│   └── formatar_modelo3.py
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
| `SLACKBOT_TEMP_DIR` | Arquivos temporários do bot |

## Observações

- Planilhas `.xlsx` de entrada/saída ficam fora do Git (`.gitignore`)
- BDI padrão nos totais: **30,62%**
- Ideal para planilhas do [i9 Orçamentos](https://www.i9orcamentos.com.br/sistema/orcamentos)
