FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1
COPY services/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY services /app/services
EXPOSE 8006
CMD ["uvicorn", "services.scoring_service.app.main:app", "--host", "0.0.0.0", "--port", "8006"]
