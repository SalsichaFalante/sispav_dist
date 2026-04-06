# 1. Imagem base leve
FROM python:3.11-slim

# 2. Evita que o Python gere arquivos .pyc e permite logs em tempo real
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# 3. Define o diretório de trabalho
WORKDIR /app

# 4. Instala dependências do sistema (se necessário para cálculos pesados)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 5. Instala as dependências do Python
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 6. Copia o restante do código
COPY . .

# 7. Cria um usuário comum para rodar a aplicação (Segurança)
RUN useradd -m sispav_user
USER sispav_user

# 8. Porta que o serviço vai usar
EXPOSE 8080

# 9. Comando de inicialização com Gunicorn (Produção)
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "4", "run:app"]