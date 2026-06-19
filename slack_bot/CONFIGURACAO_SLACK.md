# Configuração do app no Slack (caso seja necessário refazer)

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
- `commands` (comando `/i9formatar`)

### 4. Reinstalar o app
Depois de mudar escopos ou eventos:
- **Install App** → **Reinstall to Workspace**

### 5. Convidar o bot no canal
No canal de teste:
```
/invite @NomeDoSeuBot
```

### 6. Como testar

1. Envie uma planilha `.xlsx` no DM ou canal (o bot confirma o recebimento)
2. Rode `/i9formatar modelo=1` no mesmo canal/DM
3. O bot devolve o Excel formatado (e Word nos modelos 1 e 3)

| Onde | O que fazer |
|------|-------------|
| Canal | Anexe `.xlsx` → `/i9formatar modelo=1` |
| DM | Anexe `.xlsx` → `/i9formatar modelo=1` |
| Ajuda | `@Bot olá` ou `olá` no DM |
