FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1
COPY services/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY services /app/services
EXPOSE 8000
CMD ["uvicorn", "services.api_gateway.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
