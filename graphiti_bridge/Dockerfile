FROM python:3.12-slim

WORKDIR /app
COPY graphiti_bridge/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY graphiti_bridge/app.py ./app.py
EXPOSE 8008
CMD ["python", "app.py"]
