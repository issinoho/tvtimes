# syntax=docker/dockerfile:1
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml ./
COPY tvtimes_connector ./tvtimes_connector
RUN pip install --no-cache-dir .

# Run with --network host so LAN HDHomeRun discovery works.
ENTRYPOINT ["tvtimes-connector"]
CMD ["run"]
