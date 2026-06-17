# Formatador de Planilhas SINAPI

Ferramenta em Python para converter planilhas sintéticas exportadas do sistema SINAPI em modelos formatados de orçamento, com estilos, bordas, totais e valores por extenso.

## O que faz

O projeto lê uma planilha `.xlsx` de origem (formato padrão do SINAPI) e gera um novo arquivo Excel com layout profissional. Há três modelos de saída disponíveis:

| Script | Modelo | Descrição |
|--------|--------|-----------|
| `main1.py` | Modelo 1 | Tabela completa com preços e totais **com e sem BDI**. Fonte Calibri, tema verde. Inclui valores por extenso. |
| `main2.py` | Modelo 2 | Layout simplificado (sem colunas de BDI detalhado). Fonte Aptos Narrow, tema cinza. Totais calculados por fórmulas Excel (soma por seção, BDI de 30,62%, orçamento total). |
| `main3.py` | Modelo 3 | Similar ao Modelo 1, mas apenas com colunas **c/ BDI**. Gera uma segunda aba **Orçamento Resumo** com os itens principais. |

### Funcionalidades comuns

- Detecção automática do início dos dados na planilha de origem
- Formatação de seções, itens regulares e linhas de texto por extenso
- Conversão de códigos "próprio" para `Comp. SINAPI`
- Ajuste automático de altura de linhas conforme o tamanho da descrição
- Formatação monetária em Real (R$)
- Bordas e cores padronizadas por modelo
- Abertura automática do arquivo gerado no Windows

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

## Uso

1. Coloque a planilha de origem na mesma pasta do script escolhido.
2. Verifique o nome do arquivo de entrada no bloco `if __name__ == "__main__"` do script (ou altere conforme necessário).
3. Ative o ambiente virtual e execute o script desejado:

```bash
.venv\Scripts\activate
python main1.py
```

```bash
python main2.py
```

```bash
python main3.py
```

4. O arquivo formatado será salvo na mesma pasta e aberto automaticamente.

### Arquivos padrão configurados nos scripts

| Script | Arquivo de entrada | Arquivo de saída |
|--------|-------------------|------------------|
| `main1.py` | `Planilha Sintética Simples 1017 .xlsx` | `Planilha_Sintetica_Convertida_Modelo1.xlsx` |
| `main2.py` | `Planilha Sintética Simples 1017 .xlsx` | `Planilha_Sintetica_Convertida_Modelo2.xlsx` |
| `main3.py` | `Planilha Sintética Simples 1016 .xlsx` | `Planilha_Sintetica_Convertida_Modelo3.xlsx` |

Para usar outro arquivo, edite as variáveis `arquivo_origem_sistema` e `arquivo_saida_formatado` no final de cada script.

## Estrutura do projeto

```
formatador-planilhas/
├── main1.py              # Formatador — Modelo 1
├── main2.py              # Formatador — Modelo 2
├── main3.py              # Formatador — Modelo 3
├── create_venv.bat       # Configuração do ambiente (Windows)
├── requirements.txt      # Dependências Python
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

## Observações

- Arquivos `.xlsx` estão no `.gitignore` — mantenha as planilhas de entrada e saída localmente.
- O BDI padrão exibido nos totais é de **30,62%** (conforme os rótulos nos modelos).
- O Modelo 2 calcula totais por seção com fórmulas Excel; seções sem subitens recebem `A ORÇAR`.
