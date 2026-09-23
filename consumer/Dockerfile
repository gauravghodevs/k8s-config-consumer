FROM python:3.11-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN mkdir -p /var/lib/rules /etc/rules
COPY src/ /app/src/

EXPOSE 8080
CMD ["python", "src/consumer.py"]
