# Build from the skill-repo root; core-gateway is passed as a named build context (needs BuildKit):
#   docker build -f skills/account/service/Dockerfile --build-context core=../core-gateway -t crown-account .
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --from=core common/__init__.py common/__init__.py
COPY --from=core common/lib common/lib
COPY --from=core common/generated common/generated
COPY skills/__init__.py skills/__init__.py
COPY skills/account skills/account
ENV PYTHONPATH=/app:/app/common/lib:/app/common/generated/python:/app/skills/account/generated/python
EXPOSE 50056
CMD ["python", "-m", "skills.account.service.server"]
