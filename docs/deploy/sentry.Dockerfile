FROM python:3.12-slim

WORKDIR /app
COPY core/requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY core/ ./core/

CMD ["python", "core/main.py"]
