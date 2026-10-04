FROM python:3.12-slim

# Faster, cleaner Python in containers
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# ffmpeg assembles the finished video (slides + narration + burned captions);
# the DejaVu face is what the captions and slides are drawn with on Linux.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

# Install deps first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App source
COPY seo_writer.py app.py store.py site_intake.py wordpress.py ./
COPY templates ./templates
COPY static ./static
# The writer's style exemplars and the source of the voice profile. Without
# this the deployed app wrote in nobody's voice; .dockerignore alone did not
# put the folder in the image.
COPY sample-articles ./sample-articles

# Article output lives here; mounted as a Fly volume for persistence
RUN mkdir -p /app/output

EXPOSE 8080

# 1 worker only: the job runner threads live in this process, and SQLite on one
# volume is the record. gthread + timeout 0 keeps long Server-Sent Events streams
# alive during generation; each open stream holds a thread, hence 16.
CMD ["gunicorn", "--workers", "1", "--threads", "16", "--worker-class", "gthread", \
     "--timeout", "0", "--bind", "0.0.0.0:8080", "app:app"]
