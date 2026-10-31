# docker build -f common/services/Dockerfile --build-arg SERVICE=sql_generation -t crown-sql_generation .
# SERVICE = sql_generation | sql_validation | sql_execution | sop_retrieval   (build context = repository root)
FROM python:3.12-slim
ARG SERVICE=sql_generation
ENV SERVICE=${SERVICE}
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY common common
ENV PYTHONPATH=/app:/app/common/lib:/app/common/generated/python
CMD python -m common.services.${SERVICE}.server
