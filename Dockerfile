FROM python:3.11-slim

WORKDIR /app

# Copia e instala dependências primeiro (aproveita cache do Docker).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o código do bot.
COPY bot.py .
COPY web.py .
COPY .env.example .

# Cria o banco de dados persistente (volume). O Railway monta em /data.
RUN mkdir -p /data
ENV DB_FILE=/data/bot.db

# Porta usada pelo Railway.
EXPOSE 8080

# Inicia o bot + painel web juntos.
CMD ["python", "web.py"]
