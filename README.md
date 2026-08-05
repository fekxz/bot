# AloneBot

Bot de comunidade para Discord em Python, usando apenas comandos slash e banco SQLite local.

## Recursos

- Autorole e mensagem de boas-vindas por servidor.
- Painel de tickets com permissões privadas, cargo da equipe e fechamento seguro.
- O painel de Atendimento tem um menu com Dúvida, Reportar Bug, Evento, Denunciar e Senha; dentro do ticket, a equipe pode assumir ou fechar o atendimento.
- O painel de Tag YouTube abre um formulário de inscrição; as candidaturas seguem para o canal de análise configurado no código e podem ser aprovadas ou recusadas pela equipe.
- Botões persistentes: o painel e os tickets continuam funcionando após reiniciar o bot.
- Painel de regras em embed customizável.
- Limpeza de mensagens e permissões de administração.
- Configurações isoladas por servidor e salvas em `bot.db`.

## Instalação

1. Instale Python 3.10 ou superior.
2. No terminal do projeto, execute `py -m pip install -r requirements.txt`.
3. Copie `.env.example` para `.env` e informe o token do bot.
4. No [Discord Developer Portal](https://discord.com/developers/applications), abra sua aplicação, entre em **Bot** e, na seção **Privileged Gateway Intents**, ative **Server Members Intent**. Clique em **Save Changes**.
5. Convide o bot com os escopos `bot` e `applications.commands`. Dê a ele permissões para gerenciar cargos, canais e mensagens.
6. Execute `iniciar_bot.bat` (duplo clique) ou `py bot.py`.

> Para testar comandos instantaneamente, preencha `TEST_GUILD_ID` com o ID do seu servidor. Sem ele, a publicação global de comandos pode levar até uma hora.

## Configuração no Discord

1. `/config autorole cargo:@Membro`
2. `/config boasvindas canal:#entrada mensagem:Bem-vindo {member} ao {server}!`
3. `/config ticket categoria:Tickets cargo_equipe:@Suporte`
4. Publique um painel em cada canal: `/painel_ticket canal:#atendimento tipo:Atendimento`, `/painel_ticket canal:#appeal tipo:Appeal`, `/painel_ticket canal:#formulários tipo:Formulários` e `/painel_ticket canal:#solicitar-tag tipo:Tag YouTube`.
5. `/painel_regras canal:#regras titulo:Regras regras:1. Respeite todos...`

Use `/ajuda` para ver os comandos. O cargo do bot deve ficar acima do cargo configurado para autorole.

## Deploy no Railway (24h ligado)

> **Importante:** o Netlify **não** serve para hospedar bot do Discord (ele não mantém processos contínuos nem arquivos). Para deixar o bot online 24h, usamos o **Railway**, que mantém o processo rodando o tempo todo.

### Passo a passo

1. Crie um repositório no GitHub e envie estes arquivos (incluindo `web.py`, `Dockerfile`, `railway.json` e `.env.example`). **Não** envie o `bot.db` (já está no `.gitignore`).

2. Acesse [railway.app](https://railway.app) e faça login com o GitHub.

3. Clique em **New Project** → **Deploy from GitHub repo** e escolha seu repositório.

4. O Railway detecta o `railway.json`/`Dockerfile` automaticamente e começa o build.

5. Vá em **Variables** e adicione:
   - `DISCORD_TOKEN` = o token do seu bot.
   - `TEST_GUILD_ID` = (opcional) o ID de um servidor de testes.

6. **Banco de dados persistente:** para não perder tickets/configurações, vá em **Settings** → **Volumes** → **New Volume**, monte ele em `/data` e adicione a variável `DB_FILE=/data/bot.db`.

7. Depois do deploy, o Railway gera uma URL pública. Abra essa URL para ver o **painel web** do bot:
   - `/` → status e servidores conectados.
   - `/logs` → últimas linhas de log.
   - `/health` → healthcheck (usado pelo Railway para saber se está vivo).

### Testar localmente (com painel)

```bash
py -m pip install -r requirements.txt
# crie um .env com DISCORD_TOKEN e rode:
py web.py
```

O painel fica em `http://localhost:8080` e o bot roda em segundo plano no mesmo processo.
