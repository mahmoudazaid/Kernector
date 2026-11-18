FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY orders ./orders
ENV APP_ENV=production
ENV LOG_LEVEL=info
ENV DATABASE_URL=
ENV API_TOKEN=
CMD ["python", "-m", "orders"]
