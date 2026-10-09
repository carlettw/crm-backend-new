FROM python:3.12-slim
WORKDIR /code
<<<<<<< HEAD
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/code
=======
   ENV PYTHONUNBUFFERED=1 PYTHONPATH=/code
>>>>>>> 5876858963b8559a2dbd6fd188c6194280dbf876
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Render PORT beradi (lokal: 8000). Avval migratsiya, keyin server.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
