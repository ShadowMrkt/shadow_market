# shadow_market/backend/Dockerfile
# Revision History:
# 2025-04-07: Initial creation from scratch (one file at a time).
#             - Multi-stage build (builder/runtime).
#             - Uses python:3.11-slim-bookworm base image for security/size.
#             - Installs build dependencies in builder stage only.
#             - Installs runtime dependencies (using psycopg2 not -binary).
#             - Creates non-root user 'appuser' (UID 1000 chosen).
#             - Copies application code and collected static files.
#             - Sets up Gunicorn as the entrypoint.
#             - Exposes port 8000.
#             - Sets WORKDIR and copies requirements first for layer caching.
#             - Includes basic ENV vars for Python execution.

# --- Builder Stage ---
# Use a specific stable tag for the base image (slim variant for smaller size)
FROM python:3.11-slim-bookworm AS builder

# Set environment variables for consistent Python behavior and pip settings
ENV PYTHONUNBUFFERED 1
ENV PYTHONDONTWRITEBYTECODE 1
ENV PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100

# Install OS build dependencies needed for certain Python packages
# List only essential build tools. libpq-dev for psycopg2, others as needed by requirements.txt
# Using bookworm variants for apt packages to match base image
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    # Add other build deps like libsecp256k1-dev, pkg-config if strictly needed by requirements
    # Clean up apt cache afterwards to reduce layer size
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set working directory within the build stage
WORKDIR /app

# Copy requirements file first to leverage Docker build cache
COPY ./requirements.txt .

# Install Python dependencies (including Gunicorn needed for runtime stage)
# Use psycopg2 (requires libpq-dev) instead of psycopg2-binary in production builds
# Ensure gunicorn is in requirements.txt or install it explicitly here
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir gunicorn psycopg2

# Copy the entire application source code into the builder stage
COPY . .

# Collect static files using production settings
# This assumes STATIC_ROOT is configured in your settings/prod.py
# It might require dummy environment variables (like SECRET_KEY) if your settings file
# strictly requires them even for collectstatic. Avoid this dependency if possible.
# Ensure DJANGO_SETTINGS_MODULE points to your production settings.
RUN SECRET_KEY="dummy-key-for-build" DJANGO_SETTINGS_MODULE=mymarketplace.settings.prod python manage.py collectstatic --noinput --clear


# --- Runtime Stage ---
# Use the same minimal base image for the final stage
FROM python:3.11-slim-bookworm AS runtime

# Set environment variables for runtime
ENV PYTHONUNBUFFERED 1
ENV PYTHONDONTWRITEBYTECODE 1
ENV DJANGO_SETTINGS_MODULE=mymarketplace.settings.prod \
    DJANGO_ENV=production

# Create a non-root group and user with a specific UID/GID
# Using fixed IDs is good practice for managing permissions (e.g., in Kubernetes)
RUN groupadd --system --gid 1000 appgroup && \
    useradd --system --no-log-init --no-create-home --uid 1000 --gid appgroup appuser

# Create necessary directories and set ownership
# Include directories for static files and potentially media files
RUN mkdir -p /app /app/staticfiles /app/media && chown -R appuser:appgroup /app
WORKDIR /app

# Copy installed Python packages from the builder stage's site-packages
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
# Copy executables installed by pip (like gunicorn)
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy collected static files from the builder stage, ensuring correct ownership
COPY --from=builder --chown=appuser:appgroup /app/staticfiles /app/staticfiles

# Copy application code from the builder stage, ensuring correct ownership
COPY --from=builder --chown=appuser:appgroup /app .

# Switch to the non-root user
USER appuser

# Expose the port Gunicorn will run on (should match Gunicorn config)
EXPOSE 8000

# Define the command to run the application using Gunicorn
# Configuration (bind address, workers, timeout, etc.) should be passed via
# environment variables (e.g., GUNICORN_CMD_ARGS) or a config file.
# Example: GUNICORN_CMD_ARGS="-b 0.0.0.0:8000 -w 4 --timeout 60 --log-level info"
# The actual GUNICORN_CMD_ARGS variable would be set via docker-compose or Kubernetes.
CMD ["gunicorn", "mymarketplace.wsgi:application"]