FROM python:3.12-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

# Create directories
RUN mkdir -p instance uploads/attachments

ENV FLASK_APP=run.py
ENV FLASK_ENV=production

EXPOSE 5000

# Migrate DB + run (execute `flask init-db` only once during first-time setup)
CMD flask db upgrade && gunicorn -b 0.0.0.0:5000 -w 4 run:app
