
# Usa uma imagem oficial do Python como base (versão leve)
FROM python:3.11-slim

# Instala o FFmpeg e dependências do sistema
# Esta é a parte que garante que o motor de vídeo funciona no Render
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Define o diretório de trabalho dentro do servidor
WORKDIR /app

# Copia o ficheiro de dependências e instala as bibliotecas Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia todos os ficheiros do teu repositório (incluindo app.py e index.html)
COPY . .

# Cria as pastas necessárias para o processamento de vídeo
RUN mkdir -p uploads processed

# Define a porta que o Render vai utilizar
ENV PORT=10000

# Comando para iniciar o servidor usando Gunicorn (estável para produção)
# Nota: O teu ficheiro principal deve chamar-se app.py
CMD gunicorn --bind 0.0.0.0:$PORT --timeout 600 app:app
