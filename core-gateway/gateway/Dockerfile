# Build from the core-gateway root; the skill-repo is passed as a named build context (needs BuildKit):
#   docker build -f gateway/Dockerfile --build-context skills=../skill-repo -t crown-gateway .
# The gateway only reads skills/*/skill.json and skill.md plus registry/descriptors.pb; it runs no skill code.
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY common/__init__.py common/__init__.py
COPY common/lib common/lib
COPY gateway gateway
COPY registry registry
COPY --from=skills skills /skill-repo/skills
ENV PYTHONPATH=/app:/app/common/lib SKILLS_DIR=/skill-repo/skills
EXPOSE 8000
CMD ["uvicorn", "gateway.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
