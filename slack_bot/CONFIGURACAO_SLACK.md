# Configuração do app no Slack (obrigatório)

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
- **Save Changes**

> Sem esta etapa o bot conecta, mas o Slack **não envia nenhum evento** — nada aparece no terminal.

### 3. OAuth & Permissions → Bot Token Scopes
Adicione:
- `app_mentions:read`
- `chat:write`
- `files:read`
- `files:write`
- `im:history`
- `im:read`
- `commands` (se usar `/i9formatar`)

### 4. Reinstalar o app
Depois de mudar escopos ou eventos:
- **Install App** → **Reinstall to Workspace**

### 5. Convidar o bot no canal
No canal de teste:
```
/invite @NomeDoSeuBot
```

### 6. Como testar
| Onde | O que fazer |
|------|-------------|
| Canal | `@NomeDoSeuBot olá` (precisa da menção `@`) |
| DM | Abra mensagem direta com o bot e escreva `olá` |

Ao enviar mensagem, o terminal deve mostrar algo como:
```
INFO ... Evento recebido: app_mention
```

Se **nada** aparecer no terminal, volte ao passo 2 (Event Subscriptions).
