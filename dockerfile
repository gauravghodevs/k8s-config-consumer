#!/bin/bash
FROM python:3.11-slim
WORKDIR /app
COPY src/ /app/src/
ENV PYTHONUNBUFFERED=1
CMD ["python", "src/consumer.py"]
