# AEGIS API: the checks, the sandbox and Ask, with the Gemma evidence set, the approval index and the DITA-OT
# output for each reader baked in. CI builds data/approvals.json and build/packs before this image.
FROM python:3.12-slim
LABEL org.opencontainers.image.source="https://github.com/siddharthraop/AEGIS" \
      org.opencontainers.image.licenses="MIT"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 AEGIS_CORPUS=/app/corpus
WORKDIR /app
COPY pyproject.toml README.md ./
COPY aegis aegis
COPY api api
RUN pip install --no-cache-dir '.[api]' && pip uninstall -y pip
COPY packs packs
COPY corpus/gemma corpus/gemma
COPY data data
COPY build/packs build/packs
ARG CORPUS_COMMIT=main
ENV AEGIS_CORPUS_COMMIT=${CORPUS_COMMIT}
RUN useradd --uid 10001 aegis
USER aegis
EXPOSE 8080
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8080"]
