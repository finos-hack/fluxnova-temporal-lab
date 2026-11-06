FROM python:3.12-slim
WORKDIR /app
COPY temporal-worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt pytest==8.4.2 pytest-asyncio==1.2.0
COPY temporal-worker/kyc_worker ./kyc_worker
COPY temporal-worker/tests ./tests
COPY temporal-worker/pytest.ini .
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "kyc_worker.main"]
