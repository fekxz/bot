"""
Painel de controle web do AloneBot.

Roda o bot e um servidor Flask no MESMO processo, para que o painel
possa mostrar o status real do bot (online, latência, servidores,
tickets, logs etc.) enquanto ele fica ligado 24h no Railway.

Uso:
    py web.py            # inicia bot + painel
"""

import asyncio
import os
import threading

from flask import Flask, jsonify, render_template_string

import bot

app = Flask(__name__)


def run_async(coro):
    """Roda uma coroutine no event loop do bot (que roda em outra thread)."""
    loop = bot.bot.loop
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=10)


# ----------------------------------------------------------------------
# Página principal: status geral do bot
# ----------------------------------------------------------------------
@app.route("/")
def index():
    b = bot.bot
    status = "online" if b.is_ready() else "conectando"
    color = "#3fb950" if status == "online" else "#f0b429"

    guilds = list(b.guilds)
    guilds_info = [
        {"name": g.name, "members": g.member_count, "id": g.id}
        for g in guilds
    ]

    return render_template_string(TEMPLATE, status=status, color=color, guilds=guilds_info)


# ----------------------------------------------------------------------
# Rota JSON com estatísticas reais do banco de dados
# ----------------------------------------------------------------------
@app.route("/dados")
def dados():
    db = bot.bot.db

    async def _query():
        tickets_total = 0
        tickets_abertos = 0
        try:
            async with db.conn.execute("SELECT COUNT(*) FROM tickets") as cur:
                tickets_total = (await cur.fetchone())[0]
            async with db.conn.execute("SELECT COUNT(*) FROM tickets WHERE closed = 0") as cur:
                tickets_abertos = (await cur.fetchone())[0]
        except Exception:
            pass

        aplicacoes_pendentes = 0
        aplicacoes_aprovadas = 0
        try:
            async with db.conn.execute("SELECT COUNT(*) FROM creator_applications WHERE status = 'pending'") as cur:
                aplicacoes_pendentes = (await cur.fetchone())[0]
            async with db.conn.execute("SELECT COUNT(*) FROM creator_applications WHERE status = 'approved'") as cur:
                aplicacoes_aprovadas = (await cur.fetchone())[0]
        except Exception:
            pass

        return {
            "servidores": len(bot.bot.guilds),
            "tickets_total": tickets_total,
            "tickets_abertos": tickets_abertos,
            "aplicacoes_pendentes": aplicacoes_pendentes,
            "aplicacoes_aprovadas": aplicacoes_aprovadas,
        }

    try:
        data = run_async(_query())
    except Exception as exc:  # evento de loop ainda não pronto
        return jsonify({"erro": str(exc)}), 500
    return jsonify(data)


# ----------------------------------------------------------------------
# Rota de logs: últimas linhas capturadas pelo bot
# ----------------------------------------------------------------------
@app.route("/logs")
def logs():
    return jsonify({"logs": bot.LOG_BUFFER[-200:]})


# ----------------------------------------------------------------------
# Healthcheck para o Railway
# ----------------------------------------------------------------------
@app.route("/health")
def health():
    if bot.bot.is_ready():
        return jsonify({"status": "ok", "bot": "online"}), 200
    return jsonify({"status": "starting", "bot": "conectando"}), 200


TEMPLATE = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AloneBot — Painel</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', system-ui, sans-serif; background: #0d1117; color: #c9d1d9; min-height: 100vh; }
  .container { max-width: 900px; margin: 0 auto; padding: 32px 20px; }
  header { display: flex; align-items: center; gap: 14px; margin-bottom: 28px; }
  .logo { width: 48px; height: 48px; border-radius: 12px; background: linear-gradient(135deg,#5865f2,#eb459e); display:flex; align-items:center; justify-content:center; font-weight:800; font-size:20px; color:#fff; }
  h1 { font-size: 24px; }
  .badge { display:inline-block; padding:4px 12px; border-radius:999px; font-weight:700; font-size:13px; color:#fff; background:{{ color }}; }
  .card { background:#161b22; border:1px solid #30363d; border-radius:12px; padding:20px; margin-bottom:20px; }
  .card h2 { font-size:16px; margin-bottom:14px; color:#e6edf3; }
  .nav { display:flex; gap:10px; margin-bottom:20px; }
  .nav a { background:#21262d; padding:8px 16px; border-radius:8px; font-size:14px; color:#58a6ff; text-decoration:none; }
  .nav a:hover { background:#30363d; }
  ul { list-style:none; }
  li { padding:10px 0; border-bottom:1px solid #21262d; display:flex; justify-content:space-between; }
  li:last-child { border-bottom:none; }
  .muted { color:#8b949e; font-size:14px; }
  pre { background:#0d1117; border:1px solid #30363d; border-radius:8px; padding:14px; font-size:12px; overflow:auto; max-height:600px; white-space:pre-wrap; }
</style>
</head>
<body>
<div class="container">
  <header>
    <div class="logo">A</div>
    <div>
      <h1>AloneBot</h1>
      <span class="badge">{{ status }}</span>
    </div>
  </header>

  <nav class="nav">
    <a href="/">Status</a>
    <a href="/dados">Dados (JSON)</a>
    <a href="/logs">Logs</a>
    <a href="/health">Healthcheck</a>
  </nav>

  <div class="card">
    <h2>Servidores conectados ({{ guilds|length }})</h2>
    {% if guilds %}
    <ul>
      {% for g in guilds %}
      <li><span>{{ g.name }}</span><span class="muted">{{ g.members }} membros</span></li>
      {% endfor %}
    </ul>
    {% else %}
    <p class="muted">Nenhum servidor conectado ainda.</p>
    {% endif %}
  </div>
</div>
</body>
</html>
"""


def main():
    # Configura o Flask para escutar na porta do Railway (ou 8080 local).
    port = int(os.getenv("PORT", "8080"))

    # Thread: mantém o WebSocket do bot + o servidor web no mesmo processo.
    bot_thread = threading.Thread(target=bot.run_bot, daemon=True)
    bot_thread.start()

    print(f"\n[Painel] Servidor web em http://0.0.0.0:{port}")
    print("[Painel] O bot está rodando em segundo plano.\n")
    app.run(host="0.0.0.0", port=port, debug=False)


if __name__ == "__main__":
    main()
