FROM python:3.12-slim
WORKDIR /app
COPY bridge/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt pytest==8.4.2
COPY bridge/fluxnova_temporal_bridge ./fluxnova_temporal_bridge
COPY bridge/tests ./tests
COPY bridge/pytest.ini .
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "fluxnova_temporal_bridge.main"]
