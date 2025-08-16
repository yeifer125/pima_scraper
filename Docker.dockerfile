FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    wget curl unzip libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libx11-xcb1 libxcomposite1 libxdamage1 libxrandr2 \
    libgbm1 libpango-1.0-0 libpangocairo-1.0-0 libgtk-3-0 libxshmfence1 fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install playwright && playwright install

COPY . /app
WORKDIR /app

EXPOSE 5000
CMD ["python", "tu_script.py"]
