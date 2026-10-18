# Reuses the cross-platform branch's pinned Python base, without its retired skill executor.
ARG PYTHON_BASE=python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
FROM ${PYTHON_BASE}
COPY experiments/windows-sandbox/requirements.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8 MPLBACKEND=Agg
USER 10001:10001
CMD ["python", "--version"]
