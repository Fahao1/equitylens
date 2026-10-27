FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 EQUITYLENS_DATA_DIR=/data
WORKDIR /app
COPY backend/requirements.lock ./requirements.lock
RUN pip install --no-cache-dir -r requirements.lock && useradd --uid 10001 --create-home equitylens && mkdir /data && chown equitylens:equitylens /data
COPY backend/app ./app
USER equitylens
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')" || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--limit-concurrency", "32"]
