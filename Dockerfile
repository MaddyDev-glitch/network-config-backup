FROM python:3.12-slim  # Lightweight Python base image [web:1]

WORKDIR /app            # Set working directory

COPY hello.py .         # Copy your script into the container

CMD ["python", "hello.py"]  # Auto-run the script on container start [web:2]
