# Build from the skill-repo root; core-gateway is passed as a named build context (needs BuildKit):
#   docker build -f skills/transaction/service/Dockerfile --build-context core=../core-gateway -t crown-transaction .
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --from=core common/__init__.py common/__init__.py
COPY --from=core common/lib common/lib
COPY --from=core common/generated common/generated
COPY skills/__init__.py skills/__init__.py
COPY skills/transaction skills/transaction
ENV PYTHONPATH=/app:/app/common/lib:/app/common/generated/python:/app/skills/transaction/generated/python
EXPOSE 50057
CMD ["python", "-m", "skills.transaction.service.server"]
