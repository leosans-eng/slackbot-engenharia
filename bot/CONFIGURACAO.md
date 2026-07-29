# Configuração do bot Slack — slackbot-engenharia

Se o terminal mostra `Bolt app is running!` mas o bot **não responde**, quase sempre falta configurar **Event Subscriptions** no painel do Slack.

## Checklist em [api.slack.com/apps](https://api.slack.com/apps)

### 1. Socket Mode
- **Socket Mode** → **ON**
- App-Level Token com escopo `connections:write` → `SLACK_APP_TOKEN` (`xapp-...`)

### 2. Event Subscriptions (crítico)
- **Event Subscriptions** → **Enable Events** → **ON**
- Em **Subscribe to bot events**, adicione:
  - `app_mention` — quando alguém menciona `@SeuBot` em um canal
  - `message.im` — mensagens diretas (DM) com o bot
  - `message.channels` — mensagens em canais públicos (para receber planilhas anexadas)
  - `message.groups` — canais privados (opcional, se usar canais privados)
- **Save Changes**

> Sem esta etapa o bot conecta, mas o Slack **não envia nenhum evento** — nada aparece no terminal.

### 3. OAuth & Permissions → Bot Token Scopes
Adicione:
- `app_mentions:read`
- `chat:write`
- `files:read`
- `files:write`
- `users:read` (nome do usuário nos logs)
- `im:history`
- `im:read`
- `channels:history`
- `groups:history` (opcional — canais privados)
- `commands` (slash commands)

### 4. Slash Commands — criar no painel do Slack

Em **Slash Commands** → **Create New Command**, cadastre cada comando abaixo.
O Request URL pode ficar em branco no Socket Mode (o Bolt recebe via WebSocket).

| Command | Short Description | Usage Hint |
|---------|-------------------|------------|
| `/i9formatar` | Formata planilha SINAPI do i9 | `modelo=1` \| `2` \| `3` |
| `/fotos` | Baixa fotos do imóvel no Idebras | `Nome do Proprietário` ou `Nome index=2` |
| `/pericias` | Planilha de perícias finalizadas | `hoje` \| `ontem` \| `DD/MM/AAAA` |

Depois de criar ou alterar comandos/escopos:
- **Install App** → **Reinstall to Workspace**

### 5. Variáveis de ambiente (`.env`)

Copie `.env.example` para `.env` e preencha:

| Variável | Uso |
|----------|-----|
| `SLACK_BOT_TOKEN` | Token do bot (`xoxb-...`) |
| `SLACK_APP_TOKEN` | Socket Mode (`xapp-...`) |
| `LOGIN_USER` | Usuário do Idebras (para `/fotos` e `/pericias`) |
| `LOGIN_PASS` | Senha do Idebras |
| `BASE_URL` | URL do sistema (padrão: `http://andreserver:5050`) |

### 6. Convidar o bot no canal
No canal de teste:
```
/invite @NomeDoSeuBot
```

### 7. Como testar

**SINAPI**
1. Envie uma planilha `.xlsx` no DM ou canal
2. Rode `/i9formatar modelo=1` no mesmo canal/DM

**Fotos (Idebras)**
```
/fotos João da Silva
/fotos João da Silva index=2
```

**Perícias (Idebras)**
```
/pericias
/pericias ontem
/pericias 28/07/2026
```

| Onde | O que fazer |
|------|-------------|
| Canal | Anexe `.xlsx` → `/i9formatar modelo=1` |
| DM | Anexe `.xlsx` → `/i9formatar modelo=1` |
| Ajuda | `@Bot olá` ou `olá` no DM |
