# Formatador de Planilhas SINAPI

Ferramenta em Python para converter planilhas sintéticas exportadas do sistema i9 SINAPI em modelos formatados de orçamento, com estilos, bordas, totais e valores por extenso.

## O que faz

O projeto lê uma planilha `.xlsx` de origem (formato padrão do SINAPI) e gera um novo arquivo Excel com layout profissional. Há três modelos de saída disponíveis:

| Script | Modelo | Descrição |
|--------|--------|-----------|
| `main1.py` | Modelo 1 (Atualização) | Tabela completa com preços e totais **com e sem BDI**. Fonte Calibri, tema verde. Inclui valores por extenso. |
| `main2.py` | Modelo 2 (Atualização - Enviar ao Perito) | Layout simplificado (sem colunas de BDI detalhado). Fonte Aptos Narrow, tema cinza. Totais calculados por fórmulas Excel (soma por seção, BDI de 30,62%, orçamento total). |
| `main3.py` | Modelo 3 (Parecer Inicial) | Similar ao Modelo 1, mas apenas com colunas **c/ BDI**. Gera uma segunda aba **Orçamento Resumo** com os itens principais. |

### Funcionalidades comuns

- Detecção automática do início dos dados na planilha de origem
- Formatação de seções, itens regulares e linhas de texto por extenso
- Conversão de códigos "próprio" para `Comp. SINAPI`
- Ajuste automático de altura de linhas conforme o tamanho da descrição
- Formatação monetária em Real (R$)
- Bordas e cores padronizadas por modelo
- Cálculo automático no Modelo 2, de acordo com os quantitativos

## Requisitos

- Python 3.8+
- [uv](https://github.com/astral-sh/uv) (recomendado) ou `pip`
- Windows (os scripts usam `os.startfile` para abrir o Excel ao final)

## Instalação

### Opção 1 — Script automático (Windows)

Execute o arquivo `create_venv.bat` na raiz do projeto. Ele irá:

1. Criar o ambiente virtual `.venv`
2. Ativá-lo
3. Instalar as dependências de `requirements.txt`

### Opção 2 — Manual

```bash
uv venv
.venv\Scripts\activate
uv pip install -r requirements.txt
```

Ou com pip tradicional:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Uso local (CLI)

1. Coloque a planilha de origem na pasta do projeto **ou** informe o caminho na linha de comando.
2. Ative o ambiente virtual e execute o script desejado:

```bash
.venv\Scripts\activate
python main1.py
python main2.py "caminho\para\planilha.xlsx"
python main3.py --sem-abrir
```

3. O arquivo formatado será salvo na mesma pasta da origem e aberto automaticamente (Windows).

Opções disponíveis em todos os scripts: `--sem-abrir`, `--sem-word`, `--modelo` (1, 2 ou 3).

### Como a planilha de entrada é escolhida

Se você não passar o arquivo na linha de comando, a CLI resolve nesta ordem:

1. Variável de ambiente `FORMATADOR_ARQUIVO_ENTRADA`
2. Arquivo `local_config.py`
3. Detecção automática de `Planilha Sintética*.xlsx` na pasta (exclui arquivos já convertidos)

Se houver **mais de um** candidato na pasta, informe o caminho explicitamente (Ex.: python main2.py "Planilha Sintética Simples 1007 .xlsx") ou fixe em `local_config.py`.

## Uso programático (bot, scripts, automações)

```python
from formatador import Modelo, formatar_planilha

resultado = formatar_planilha(
    "planilha.xlsx",
    modelo=Modelo.ATUALIZACAO,
    diretorio_saida="/tmp/saida",  # opcional
    gerar_word=True,               # opcional; padrão automático por modelo
)

print(resultado.caminho_excel)
print(resultado.caminho_word)  # modelos 1 e 3
```

## Bot Slack (estrutura preparada)

O diretório `slack_bot/` contém o esqueleto para integração futura. Para instalar dependências do bot:

```bash
pip install -r requirements-bot.txt
cp .env.example .env
# preencha SLACK_BOT_TOKEN e SLACK_APP_TOKEN
python -m slack_bot.app
```

A lógica de processamento reutiliza `formatador.formatar_planilha` via `slack_bot.handlers.processar_upload`.

**Bot não responde?** Veja [`slack_bot/CONFIGURACAO_SLACK.md`](slack_bot/CONFIGURACAO_SLACK.md).

**Uso:** envie um `.xlsx` no canal ou DM → `/i9formatar modelo=1` (ou `2`, `3`).

## Estrutura do projeto

```
formatador-planilhas/
├── formatador/           # Lógica de formatação (reutilizável)
│   ├── comum.py
│   ├── entrada.py        # Resolução do arquivo de entrada (CLI)
│   ├── modelo1.py
│   ├── modelo2.py
│   ├── modelo3.py
│   ├── service.py        # formatar_planilha()
│   └── cli.py
├── slack_bot/            # Esqueleto do bot Slack
│   ├── app.py
│   ├── config.py
│   └── handlers.py
├── main1.py              # CLI local — Modelo 1
├── main2.py              # CLI local — Modelo 2
├── main3.py              # CLI local — Modelo 3
├── exportar_word_modelo1.py
├── exportar_word_modelo3.py
├── modelos/              # Templates
├── local_config.example.py
├── create_venv.bat
├── requirements.txt
├── requirements-bot.txt
└── README.md
```

## Dependências

| Pacote | Uso |
|--------|-----|
| [openpyxl](https://openpyxl.readthedocs.io/) | Leitura e escrita de arquivos Excel |
| [num2words](https://github.com/savoirfairelinux/num2words) | Conversão de valores numéricos para extenso (pt_BR) |
| docopt | Dependência transitiva |

## Planilha de origem

A planilha de entrada deve ser uma exportação sintética do SINAPI contendo, entre outras colunas:

- **Item**, **Banco**, **Código**, **Descrição**, **Un.**, **Qtd.**
- Preços e totais com e sem BDI

O formatador localiza automaticamente a linha de cabeçalho `Item` e processa os dados a partir da linha seguinte.

É **ideal** e principalmente pensado para planilhas geradas do [i9 Orçamentos](https://www.i9orcamentos.com.br/sistema/orcamentos).

## Observações

- Arquivos `.xlsx` estão no `.gitignore` — mantenha as planilhas de entrada e saída localmente.
- O BDI padrão exibido nos totais é de **30,62%**, mesmo se alterados no i9 (conforme os rótulos nos modelos). Para o caso de alteração, deve ser feita em seus devidos scripts.
- O Modelo 2 calcula totais por seção com fórmulas Excel; seções sem subitens recebem `A ORÇAR`.
