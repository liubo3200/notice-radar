FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

ENV PORT=8000
EXPOSE 8000

# 单页演示应用，2 个 worker 够用；timeout 放宽，LLM 通道可能慢
CMD gunicorn -b 0.0.0.0:${PORT} -w 2 --timeout 60 app:app
