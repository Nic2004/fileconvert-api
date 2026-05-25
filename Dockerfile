FROM python:3.11-slim

# Instalează LibreOffice + dependențe sistem
RUN apt-get update && apt-get install -y \
    libreoffice \
    libreoffice-writer \
    libreoffice-calc \
    libreoffice-impress \
    poppler-utils \
    fonts-liberation \
    fonts-dejavu \
    --no-install-recommends \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instalează dependențele Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiază codul
COPY main.py .

# Crează directorul temporar
RUN mkdir -p /tmp/fileconvert

# Port pe care ascultă serverul
EXPOSE 8000

# Pornire server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
