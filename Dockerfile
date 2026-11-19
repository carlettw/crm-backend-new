FROM python:3.12-slim
WORKDIR /code
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/code
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# root bo'lmagan foydalanuvchi bilan ishlaydi
RUN useradd -r -u 10001 app && chown -R app /code
USER app
# Render PORT beradi (lokal: 8000). Avval migratsiya, keyin server.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
