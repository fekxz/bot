import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Optional

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

# Buffer de logs usado pelo painel web (web.py).
LOG_BUFFER = []


class BufferHandler(logging.Handler):
    def emit(self, record):
        try:
            LOG_BUFFER.append(self.format(record))
            if len(LOG_BUFFER) > 500:
                del LOG_BUFFER[:100]
        except Exception:
            pass


logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
log = logging.getLogger("alonebot")
log.addHandler(BufferHandler())

DB_FILE = os.getenv("DB_FILE", "bot.db")
EMBED_COLOR = discord.Color.blurple()
CREATOR_REVIEW_CHANNEL_ID = 1533949161504772289
TICKET_PROFILES = {
    "atendimento": {"label": "Atendimento", "emoji": "💬", "description": "Abra um ticket para falar com a equipe."},
    "appeal": {"label": "Appeal", "emoji": "📨", "description": "Abra um pedido de revisão de punição."},
    "formularios": {"label": "Formulários", "emoji": "📄", "description": "Abra um ticket para enviar ou preencher um formulário."},
    "tag_yt": {"label": "Tag YouTube", "emoji": "▶️", "description": "Abra um ticket para solicitar sua tag de YouTube."},
}
ATENDIMENTO_OPTIONS = {
    "duvida": {"label": "Dúvida", "emoji": "❔", "description": "Se você tem alguma pergunta."},
    "bug": {"label": "Reportar Bug", "emoji": "🐞", "description": "Se encontrou algo quebrado ou com erro."},
    "evento": {"label": "Evento", "emoji": "🎉", "description": "Se for sobre eventos do servidor."},
    "denunciar": {"label": "Denunciar", "emoji": "🚩", "description": "Se alguém fez algo errado."},
    "senha": {"label": "Senha", "emoji": "🔒", "description": "Se esqueceu ou precisa de ajuda com senha."},
}
TAG_OPTIONS = {
    "youtuber": {"label": "YouTuber", "emoji": "▶️", "description": "Se você faz vídeos, shorts ou lives no YouTube."},
    "tiktoker": {"label": "TikToker", "emoji": "🎵", "description": "Se você faz vídeos ou lives no TikTok."},
    "streamer": {"label": "Streamer", "emoji": "📺", "description": "Se você faz lives na Twitch ou outras plataformas."},
}


def ticket_info(ticket_type: str) -> dict:
    if ticket_type in ATENDIMENTO_OPTIONS:
        return ATENDIMENTO_OPTIONS[ticket_type]
    if ticket_type in TAG_OPTIONS:
        return TAG_OPTIONS[ticket_type]
    return TICKET_PROFILES[ticket_type]


class Database:
    def __init__(self, path: str):
        self.path = path

    async def connect(self) -> None:
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id INTEGER PRIMARY KEY,
                autorole_id INTEGER,
                welcome_channel_id INTEGER,
                welcome_message TEXT,
                ticket_category_id INTEGER,
                ticket_staff_role_id INTEGER,
                ticket_counter INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS tickets (
                channel_id INTEGER PRIMARY KEY,
                guild_id INTEGER NOT NULL,
                owner_id INTEGER NOT NULL,
                closed INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS creator_applications (
                review_message_id INTEGER PRIMARY KEY,
                guild_id INTEGER NOT NULL,
                applicant_id INTEGER NOT NULL,
                nickname TEXT NOT NULL,
                modality TEXT NOT NULL,
                channel_link TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
            );
        """)
        # Migração para bancos criados antes do sistema de assumir ticket.
        try:
            await self.conn.execute("ALTER TABLE tickets ADD COLUMN claimed_by INTEGER")
        except aiosqlite.OperationalError:
            pass
        await self.conn.commit()

    async def close(self) -> None:
        await self.conn.close()

    async def ensure_guild(self, guild_id: int) -> None:
        await self.conn.execute("INSERT OR IGNORE INTO guild_settings (guild_id) VALUES (?)", (guild_id,))
        await self.conn.commit()

    async def settings(self, guild_id: int) -> aiosqlite.Row:
        await self.ensure_guild(guild_id)
        async with self.conn.execute("SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,)) as cursor:
            return await cursor.fetchone()

    async def set_setting(self, guild_id: int, column: str, value) -> None:
        allowed = {"autorole_id", "welcome_channel_id", "welcome_message", "ticket_category_id", "ticket_staff_role_id"}
        if column not in allowed:
            raise ValueError("Configuração inválida")
        await self.ensure_guild(guild_id)
        await self.conn.execute(f"UPDATE guild_settings SET {column} = ? WHERE guild_id = ?", (value, guild_id))
        await self.conn.commit()

    async def next_ticket_number(self, guild_id: int) -> int:
        await self.ensure_guild(guild_id)
        await self.conn.execute("UPDATE guild_settings SET ticket_counter = ticket_counter + 1 WHERE guild_id = ?", (guild_id,))
        await self.conn.commit()
        row = await self.settings(guild_id)
        return row["ticket_counter"]

    async def add_ticket(self, channel_id: int, guild_id: int, owner_id: int) -> None:
        await self.conn.execute("INSERT INTO tickets (channel_id, guild_id, owner_id) VALUES (?, ?, ?)", (channel_id, guild_id, owner_id))
        await self.conn.commit()

    async def ticket(self, channel_id: int) -> Optional[aiosqlite.Row]:
        async with self.conn.execute("SELECT * FROM tickets WHERE channel_id = ?", (channel_id,)) as cursor:
            return await cursor.fetchone()

    async def close_ticket(self, channel_id: int) -> None:
        await self.conn.execute("UPDATE tickets SET closed = 1 WHERE channel_id = ?", (channel_id,))
        await self.conn.commit()

    async def claim_ticket(self, channel_id: int, member_id: int) -> bool:
        cursor = await self.conn.execute(
            "UPDATE tickets SET claimed_by = ? WHERE channel_id = ? AND claimed_by IS NULL AND closed = 0",
            (member_id, channel_id),
        )
        await self.conn.commit()
        return cursor.rowcount == 1

    async def add_application(self, review_message_id: int, guild_id: int, applicant_id: int, nickname: str, modality: str, channel_link: str) -> None:
        await self.conn.execute(
            "INSERT INTO creator_applications (review_message_id, guild_id, applicant_id, nickname, modality, channel_link) VALUES (?, ?, ?, ?, ?, ?)",
            (review_message_id, guild_id, applicant_id, nickname, modality, channel_link),
        )
        await self.conn.commit()

    async def application(self, review_message_id: int) -> Optional[aiosqlite.Row]:
        async with self.conn.execute("SELECT * FROM creator_applications WHERE review_message_id = ?", (review_message_id,)) as cursor:
            return await cursor.fetchone()

    async def decide_application(self, review_message_id: int, status: str) -> bool:
        cursor = await self.conn.execute(
            "UPDATE creator_applications SET status = ? WHERE review_message_id = ? AND status = 'pending'",
            (status, review_message_id),
        )
        await self.conn.commit()
        return cursor.rowcount == 1

    async def pending_applications(self) -> list[aiosqlite.Row]:
        async with self.conn.execute("SELECT * FROM creator_applications WHERE status = 'pending'") as cursor:
            return await cursor.fetchall()


class TicketOpenButton(discord.ui.Button):
    def __init__(self, profile: str):
        info = TICKET_PROFILES[profile]
        super().__init__(label=f"Abrir: {info['label']}", emoji=info["emoji"], style=discord.ButtonStyle.primary, custom_id=f"tickets:open:{profile}:v2")
        self.profile = profile

    async def callback(self, interaction: discord.Interaction):
        await self.view.open_ticket(interaction)


class AtendimentoSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=info["label"], value=key, emoji=info["emoji"], description=info["description"])
            for key, info in ATENDIMENTO_OPTIONS.items()
        ]
        super().__init__(placeholder="Escolha o que você precisa", min_values=1, max_values=1, options=options, custom_id="tickets:openmenu:atendimento:v1")

    async def callback(self, interaction: discord.Interaction):
        await self.view.open_ticket(interaction, self.values[0])


class TagSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=info["label"], value=key, emoji=info["emoji"], description=info["description"])
            for key, info in TAG_OPTIONS.items()
        ]
        super().__init__(placeholder="Selecione sua modalidade", min_values=1, max_values=1, options=options, custom_id="tickets:openmenu:tag-yt:v1")

    async def callback(self, interaction: discord.Interaction):
        await self.view.open_creator_form(interaction, self.values[0])


class CreatorApplicationModal(discord.ui.Modal):
    def __init__(self, bot: "CommunityBot", modality: str):
        super().__init__(title="Formulário de Inscrição")
        self.bot = bot
        self.modality = modality
        self.nickname = discord.ui.TextInput(label="Seu nick", placeholder="Seu nick no servidor", max_length=32)
        self.channel_link = discord.ui.TextInput(label=f"Link do seu canal ({TAG_OPTIONS[modality]['label']})", placeholder="https://...", max_length=300)
        self.add_item(self.nickname)
        self.add_item(self.channel_link)

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Envie o formulário dentro do servidor.", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        review_channel = self.bot.get_channel(CREATOR_REVIEW_CHANNEL_ID)
        if not isinstance(review_channel, discord.TextChannel):
            try:
                review_channel = await self.bot.fetch_channel(CREATOR_REVIEW_CHANNEL_ID)
            except discord.HTTPException:
                review_channel = None
        if not isinstance(review_channel, discord.TextChannel):
            return await interaction.followup.send("O canal de análise não foi encontrado ou o bot não tem acesso a ele.", ephemeral=True)

        info = TAG_OPTIONS[self.modality]
        embed = discord.Embed(title="📋 Nova inscrição de criador", color=discord.Color.purple())
        embed.add_field(name="Candidato", value=f"{interaction.user.mention}\nID: `{interaction.user.id}`", inline=True)
        embed.add_field(name="Modalidade", value=f"{info['emoji']} {info['label']}", inline=True)
        embed.add_field(name="Nick", value=self.nickname.value, inline=False)
        embed.add_field(name="Canal", value=self.channel_link.value, inline=False)
        embed.set_footer(text="Use os botões abaixo para analisar esta candidatura.")
        message = await review_channel.send(embed=embed)
        await self.bot.db.add_application(message.id, interaction.guild.id, interaction.user.id, self.nickname.value, self.modality, self.channel_link.value)
        await message.edit(view=CreatorReviewPanel(self.bot, message.id))
        await interaction.followup.send("Sua inscrição foi enviada para análise. Boa sorte!", ephemeral=True)


class CreatorReviewButton(discord.ui.Button):
    def __init__(self, review_message_id: int, decision: str):
        approved = decision == "approved"
        super().__init__(
            label="Aprovar" if approved else "Recusar",
            emoji="✅" if approved else "❌",
            style=discord.ButtonStyle.success if approved else discord.ButtonStyle.danger,
            custom_id=f"creator-review:{decision}:{review_message_id}:v1",
        )
        self.decision = decision

    async def callback(self, interaction: discord.Interaction):
        await self.view.review(interaction, self.decision)


class CreatorReviewPanel(discord.ui.View):
    def __init__(self, bot: "CommunityBot", review_message_id: int):
        super().__init__(timeout=None)
        self.bot = bot
        self.review_message_id = review_message_id
        self.add_item(CreatorReviewButton(review_message_id, "approved"))
        self.add_item(CreatorReviewButton(review_message_id, "rejected"))

    async def review(self, interaction: discord.Interaction, decision: str):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Use este botão no servidor.", ephemeral=True)
        settings = await self.bot.db.settings(interaction.guild.id)
        if not can_manage_ticket(interaction.user, settings["ticket_staff_role_id"]):
            return await interaction.response.send_message("Apenas a equipe pode analisar candidaturas.", ephemeral=True)
        application = await self.bot.db.application(self.review_message_id)
        if not application or application["status"] != "pending":
            return await interaction.response.send_message("Esta candidatura já foi analisada.", ephemeral=True)
        if not await self.bot.db.decide_application(self.review_message_id, decision):
            return await interaction.response.send_message("Esta candidatura acabou de ser analisada por outra pessoa.", ephemeral=True)

        approved = decision == "approved"
        color = discord.Color.green() if approved else discord.Color.red()
        result = "APROVADA" if approved else "RECUSADA"
        if interaction.message and interaction.message.embeds:
            embed = interaction.message.embeds[0]
            embed.color = color
            embed.add_field(name="Resultado", value=f"{result} por {interaction.user.mention}", inline=False)
            await interaction.message.edit(embed=embed, view=None)

        if approved:
            try:
                member = interaction.guild.get_member(application["applicant_id"]) or await interaction.guild.fetch_member(application["applicant_id"])
                modality = TAG_OPTIONS[application["modality"]]["label"]
                dm = discord.Embed(
                    title="🎉 Parabéns, você foi aprovado!",
                    description=f"Sua inscrição para **{modality}** foi aprovada pela equipe de {interaction.guild.name}.",
                    color=discord.Color.green(),
                )
                dm.add_field(name="Próximos passos", value="A equipe poderá entrar em contato para concluir a entrega dos benefícios.")
                await member.send(embed=dm)
                dm_status = "A pessoa foi avisada no privado."
            except (discord.Forbidden, discord.HTTPException, discord.NotFound):
                dm_status = "Aprovada, mas não foi possível enviar DM (privado fechado ou membro ausente)."
        else:
            dm_status = "Candidatura marcada como recusada."
        await interaction.response.send_message(dm_status, ephemeral=True)


class TicketPanel(discord.ui.View):
    def __init__(self, bot: "CommunityBot", profile: str):
        super().__init__(timeout=None)
        self.bot = bot
        self.profile = profile
        if profile == "atendimento":
            self.add_item(AtendimentoSelect())
        elif profile == "tag_yt":
            self.add_item(TagSelect())
        else:
            self.add_item(TicketOpenButton(profile))

    async def open_creator_form(self, interaction: discord.Interaction, modality: str):
        await interaction.response.send_modal(CreatorApplicationModal(self.bot, modality))

    async def open_ticket(self, interaction: discord.Interaction, selected_type: Optional[str] = None):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Use este painel dentro de um servidor.", ephemeral=True)
        # A criação de canal pode levar mais de 3 segundos; confirma a interação primeiro.
        await interaction.response.defer(ephemeral=True, thinking=True)
        settings = await self.bot.db.settings(interaction.guild.id)
        category = interaction.guild.get_channel(settings["ticket_category_id"]) if settings["ticket_category_id"] else None
        if not isinstance(category, discord.CategoryChannel):
            return await interaction.followup.send("O sistema de tickets ainda não foi configurado.", ephemeral=True)

        ticket_type = selected_type or self.profile
        profile_info = ticket_info(ticket_type)
        existing = [c for c in category.text_channels if c.topic and f"ticket-owner:{interaction.user.id};ticket-type:{ticket_type}" in c.topic]
        if existing:
            return await interaction.followup.send(f"Você já possui um ticket de {profile_info['label']} aberto: {existing[0].mention}", ephemeral=True)

        staff_role = interaction.guild.get_role(settings["ticket_staff_role_id"]) if settings["ticket_staff_role_id"] else None
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            interaction.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        number = await self.bot.db.next_ticket_number(interaction.guild.id)
        safe_name = re.sub(r"[^a-z0-9-]", "", interaction.user.name.lower().replace(" ", "-"))[:20] or "usuario"
        channel = await category.create_text_channel(
            name=f"{ticket_type}-{number:04d}-{safe_name}",
            topic=f"ticket-owner:{interaction.user.id};ticket-type:{ticket_type}",
            overwrites=overwrites,
            reason=f"Ticket aberto por {interaction.user}",
        )
        await self.bot.db.add_ticket(channel.id, interaction.guild.id, interaction.user.id)
        embed = discord.Embed(title=f"Ticket: {profile_info['label']}", description=f"Olá, {interaction.user.mention}! {profile_info['description']}", color=EMBED_COLOR)
        embed.set_footer(text="Use o botão abaixo para fechar este ticket.")
        await channel.send(content=staff_role.mention if staff_role else None, embed=embed, view=TicketActionPanel(self.bot))
        await interaction.followup.send(f"Ticket criado: {channel.mention}", ephemeral=True)


class TicketClosePanel(discord.ui.View):
    def __init__(self, bot: "CommunityBot"):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Fechar ticket", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="tickets:close:v1")
    async def close(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not interaction.guild or not interaction.channel:
            return
        ticket = await self.bot.db.ticket(interaction.channel.id)
        if not ticket or ticket["closed"]:
            return await interaction.response.send_message("Este não é um ticket aberto.", ephemeral=True)
        settings = await self.bot.db.settings(interaction.guild.id)
        staff_role_id = settings["ticket_staff_role_id"]
        is_staff = staff_role_id and isinstance(interaction.user, discord.Member) and interaction.user.get_role(staff_role_id)
        if interaction.user.id != ticket["owner_id"] and not is_staff and not interaction.user.guild_permissions.manage_channels:
            return await interaction.response.send_message("Apenas o autor, a equipe ou administradores podem fechar.", ephemeral=True)
        await self.bot.db.close_ticket(interaction.channel.id)
        await interaction.response.send_message("Ticket fechado. Este canal será apagado em 5 segundos.")
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete(reason=f"Ticket fechado por {interaction.user}")
        except discord.HTTPException:
            pass


def can_manage_ticket(member: discord.Member, staff_role_id: Optional[int]) -> bool:
    is_team = bool(staff_role_id and member.get_role(staff_role_id))
    permissions = member.guild_permissions
    return is_team or permissions.administrator or permissions.manage_channels or permissions.manage_messages


class TicketActionSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Assumir ticket", value="claim", emoji="✋", description="Atender este ticket como membro da equipe"),
            discord.SelectOption(label="Fechar ticket", value="close", emoji="🔒", description="Fechar e apagar este ticket"),
        ]
        super().__init__(placeholder="Ações do ticket", min_values=1, max_values=1, options=options, custom_id="tickets:actions:v1")

    async def callback(self, interaction: discord.Interaction):
        await self.view.handle_action(interaction, self.values[0])


class LegacyTicketActionPanel(discord.ui.View):
    def __init__(self, bot: "CommunityBot"):
        super().__init__(timeout=None)
        self.bot = bot
        self.add_item(TicketActionSelect())

    async def handle_action(self, interaction: discord.Interaction, action: str):
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not interaction.channel:
            return await interaction.response.send_message("Use este menu dentro de um ticket.", ephemeral=True)
        ticket = await self.bot.db.ticket(interaction.channel.id)
        if not ticket or ticket["closed"]:
            return await interaction.response.send_message("Este ticket não está aberto.", ephemeral=True)
        settings = await self.bot.db.settings(interaction.guild.id)
        is_team = can_manage_ticket(interaction.user, settings["ticket_staff_role_id"])

        if action == "claim":
            if not is_team:
                return await interaction.response.send_message("Somente administradores, moderadores ou a equipe podem assumir tickets.", ephemeral=True)
            if ticket["claimed_by"]:
                claimed_by = interaction.guild.get_member(ticket["claimed_by"])
                name = claimed_by.mention if claimed_by else "outro membro da equipe"
                return await interaction.response.send_message(f"Este ticket já foi assumido por {name}.", ephemeral=True)
            if not await self.bot.db.claim_ticket(interaction.channel.id, interaction.user.id):
                return await interaction.response.send_message("Este ticket acabou de ser assumido por outra pessoa.", ephemeral=True)
            await interaction.response.send_message(f"{interaction.user.mention} assumiu este ticket.")
            return

        # O dono pode fechar o próprio ticket; equipe também pode fechar qualquer um.
        if interaction.user.id != ticket["owner_id"] and not is_team:
            return await interaction.response.send_message("Apenas o autor ou a equipe podem fechar este ticket.", ephemeral=True)
        await self.bot.db.close_ticket(interaction.channel.id)
        await interaction.response.send_message("Ticket fechado. Este canal será apagado em 5 segundos.")
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete(reason=f"Ticket fechado por {interaction.user}")
        except discord.HTTPException:
            pass


class TicketActionButton(discord.ui.Button):
    def __init__(self, action: str):
        is_close = action == "close"
        super().__init__(
            label="Fechar ticket" if is_close else "Assumir ticket",
            emoji="🔒" if is_close else "✋",
            style=discord.ButtonStyle.danger if is_close else discord.ButtonStyle.success,
            custom_id=f"tickets:{action}:v2",
        )
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        await self.view.handle_action(interaction, self.action)


class TicketActionPanel(LegacyTicketActionPanel):
    def __init__(self, bot: "CommunityBot"):
        # Não chama o __init__ antigo: tickets novos devem ter apenas dois botões.
        discord.ui.View.__init__(self, timeout=None)
        self.bot = bot
        self.add_item(TicketActionButton("claim"))
        self.add_item(TicketActionButton("close"))


class CommunityBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        # O bot usa somente slash commands; não precisa ler mensagens comuns.
        intents.message_content = False
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        self.db = Database(DB_FILE)

    async def setup_hook(self):
        await self.db.connect()
        for profile in TICKET_PROFILES:
            self.add_view(TicketPanel(self, profile))
        self.add_view(TicketClosePanel(self))
        self.add_view(LegacyTicketActionPanel(self))
        self.add_view(TicketActionPanel(self))
        for application in await self.db.pending_applications():
            self.add_view(CreatorReviewPanel(self, application["review_message_id"]))
        test_guild = os.getenv("TEST_GUILD_ID")
        if test_guild and test_guild.isdigit():
            guild = discord.Object(id=int(test_guild))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("Comandos sincronizados no servidor de testes %s", test_guild)
        else:
            await self.tree.sync()
            log.info("Comandos globais sincronizados")

    async def close(self):
        if hasattr(self, "db") and hasattr(self.db, "conn"):
            await self.db.close()
        await super().close()


bot = CommunityBot()


def admin_only():
    return app_commands.checks.has_permissions(manage_guild=True)


@bot.event
async def on_ready():
    log.info("Conectado como %s (%s)", bot.user, bot.user.id)
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="/ajuda"))


@bot.event
async def on_member_join(member: discord.Member):
    settings = await bot.db.settings(member.guild.id)
    role = member.guild.get_role(settings["autorole_id"]) if settings["autorole_id"] else None
    if role:
        try:
            await member.add_roles(role, reason="Autorole")
        except discord.Forbidden:
            log.warning("Sem permissão para atribuir o cargo em %s", member.guild.id)
    channel = member.guild.get_channel(settings["welcome_channel_id"]) if settings["welcome_channel_id"] else None
    if isinstance(channel, discord.TextChannel):
        text = settings["welcome_message"] or "Bem-vindo(a), {member}!"
        await channel.send(text.replace("{member}", member.mention).replace("{server}", member.guild.name))


@bot.tree.command(name="ajuda", description="Mostra os comandos disponíveis")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(title="Central de ajuda", color=EMBED_COLOR)
    embed.add_field(name="Membros", value="`/ajuda`", inline=False)
    embed.add_field(name="Administração", value="`/config autorole`, `/config boasvindas`, `/config ticket`, `/painel_ticket tipo:...`, `/painel_regras`, `/limpar`", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


config = app_commands.Group(name="config", description="Configurações do servidor")
bot.tree.add_command(config)


@config.command(name="autorole", description="Define o cargo automático de novos membros")
@admin_only()
async def config_autorole(interaction: discord.Interaction, cargo: discord.Role):
    if not interaction.guild:
        return
    if cargo >= interaction.guild.me.top_role:
        return await interaction.response.send_message("Meu cargo precisa estar acima do cargo selecionado.", ephemeral=True)
    await bot.db.set_setting(interaction.guild.id, "autorole_id", cargo.id)
    await interaction.response.send_message(f"Autorole definido para {cargo.mention}.", ephemeral=True)


@config.command(name="boasvindas", description="Configura a mensagem de entrada")
@admin_only()
async def config_welcome(interaction: discord.Interaction, canal: discord.TextChannel, mensagem: str):
    if not interaction.guild:
        return
    await bot.db.set_setting(interaction.guild.id, "welcome_channel_id", canal.id)
    await bot.db.set_setting(interaction.guild.id, "welcome_message", mensagem)
    await interaction.response.send_message("Boas-vindas configuradas. Use `{member}` e `{server}` na mensagem.", ephemeral=True)


@config.command(name="ticket", description="Configura categoria e cargo da equipe de tickets")
@admin_only()
async def config_ticket(interaction: discord.Interaction, categoria: discord.CategoryChannel, cargo_equipe: discord.Role):
    if not interaction.guild:
        return
    await bot.db.set_setting(interaction.guild.id, "ticket_category_id", categoria.id)
    await bot.db.set_setting(interaction.guild.id, "ticket_staff_role_id", cargo_equipe.id)
    await interaction.response.send_message("Tickets configurados com sucesso.", ephemeral=True)


@bot.tree.command(name="painel_ticket", description="Envia o painel persistente para abrir tickets")
@app_commands.default_permissions(manage_guild=True)
@admin_only()
@app_commands.choices(tipo=[
    app_commands.Choice(name="Atendimento", value="atendimento"),
    app_commands.Choice(name="Appeal", value="appeal"),
    app_commands.Choice(name="Formulários", value="formularios"),
    app_commands.Choice(name="Tag YouTube", value="tag_yt"),
])
async def ticket_panel(interaction: discord.Interaction, canal: discord.TextChannel, tipo: app_commands.Choice[str]):
    settings = await bot.db.settings(interaction.guild.id)
    if not settings["ticket_category_id"]:
        return await interaction.response.send_message("Use `/config ticket` antes de publicar o painel.", ephemeral=True)
    profile = TICKET_PROFILES[tipo.value]
    if tipo.value == "atendimento":
        embed = discord.Embed(title="💬 ATENDIMENTO", description="Selecione abaixo o assunto do seu atendimento.", color=EMBED_COLOR)
        embed.set_footer(text="Escolha uma opção abaixo para abrir seu ticket privado.")
    elif tipo.value == "tag_yt":
        embed = discord.Embed(
            title="▶️ SEJA UM CRIADOR DE CONTEÚDO!",
            description="Se você produz conteúdos sobre o servidor e quer se tornar um criador, selecione sua modalidade abaixo.",
            color=discord.Color.purple(),
        )
        embed.add_field(name="📋 Requisitos — YouTube", value="• 3.000 visualizações em vídeos ou 70.000 em Shorts nos últimos 15 dias;\n• Conteúdo relacionado a Minecraft;\n• Boa qualidade de vídeo e edição.", inline=False)
        embed.add_field(name="🎵 Requisitos — TikTok", value="• 20.000 visualizações nos últimos 15 dias;\n• Conteúdo relacionado a Minecraft;\n• Boa qualidade de vídeo e edição.", inline=False)
        embed.add_field(name="📺 Requisitos — Streamer", value="• Média de 15 espectadores simultâneos;\n• Pelo menos 3 lives por semana;\n• 15 horas de live nos últimos 7 dias.", inline=False)
        embed.add_field(name="🎁 Benefícios", value="• Tag/medalha exclusiva de Criador;\n• Permissão para usar /nick;\n• Vantagens na Tag Alone e tags comemorativas;\n• Contato mais próximo com a equipe.", inline=False)
        embed.add_field(name="⚠️ Informações importantes", value="Apenas conteúdos no servidor contam para análise. O canal deve estar vinculado ao seu Discord. Cumprir os requisitos não garante aprovação.", inline=False)
        embed.set_footer(text="↓ Selecione abaixo sua modalidade ↓")
    else:
        embed = discord.Embed(title=profile["label"], description=profile["description"], color=EMBED_COLOR)
        embed.set_footer(text="Clique no botão abaixo para abrir seu ticket privado.")
    await canal.send(embed=embed, view=TicketPanel(bot, tipo.value))
    await interaction.response.send_message(f"Painel enviado em {canal.mention}.", ephemeral=True)


@bot.tree.command(name="painel_regras", description="Envia um painel de regras em embed")
@app_commands.default_permissions(manage_guild=True)
@admin_only()
async def rules_panel(interaction: discord.Interaction, canal: discord.TextChannel, titulo: str, regras: str):
    embed = discord.Embed(title=titulo, description=regras, color=discord.Color.gold())
    embed.set_footer(text=f"Regras de {interaction.guild.name}")
    await canal.send(embed=embed)
    await interaction.response.send_message(f"Painel de regras enviado em {canal.mention}.", ephemeral=True)


@bot.tree.command(name="limpar", description="Apaga mensagens recentes")
@app_commands.default_permissions(manage_messages=True)
@app_commands.checks.has_permissions(manage_messages=True)
@app_commands.describe(quantidade="De 1 a 100 mensagens")
async def purge(interaction: discord.Interaction, quantidade: app_commands.Range[int, 1, 100]):
    if not isinstance(interaction.channel, discord.TextChannel):
        return await interaction.response.send_message("Use em um canal de texto.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=quantidade)
    await interaction.followup.send(f"Apaguei {len(deleted)} mensagens.", ephemeral=True)


@bot.tree.error
async def command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        message = "Você não tem permissão para usar este comando."
    else:
        log.exception("Erro em comando", exc_info=error)
        message = "Ocorreu um erro ao executar o comando."
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


def run_bot() -> None:
    """Inicia o bot. Usado pelo painel web (web.py) em uma thread."""
    token = os.getenv("DISCORD_TOKEN")
    if not token or token in ("cole_o_token_aqui", ""):
        log.error("DISCORD_TOKEN não configurado. Defina no .env ou nas variáveis do Railway.")
        return
    while True:
        try:
            bot.run(token, log_handler=None)
        except discord.LoginFailure as error:
            log.error("Falha de login: token inválido (%s)", error)
            return
        except (discord.HTTPException, discord.ConnectionClosed, asyncio.TimeoutError, OSError) as error:
            log.warning("Erro de conexão, tentando novamente em 5s: %s", error)
            time.sleep(5)
        except KeyboardInterrupt:
            log.info("Bot encerrado manualmente.")
            return
        except Exception as error:
            log.exception("Erro inesperado no bot: %s", error)
            time.sleep(5)


if __name__ == "__main__":
    run_bot()
