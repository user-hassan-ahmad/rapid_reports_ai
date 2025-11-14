# Use Python 3.11 base image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install Poetry
RUN pip install poetry

# Copy Poetry files
COPY backend/pyproject.toml backend/poetry.lock ./

# Configure Poetry to not create virtual environment
RUN poetry config virtualenvs.create false

# Install dependencies
RUN poetry install --no-dev

# Copy application code
COPY backend/ ./backend/

# Set Python path
ENV PYTHONPATH=/app/backend/src

# Expose port
EXPOSE 8000

# Run the application
CMD ["poetry", "run", "python", "-m", "rapid_reports_ai.main"]

