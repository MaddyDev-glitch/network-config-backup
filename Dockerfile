FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY devices.yaml snapshotd.py ./

# Declare the output directory as a mount point
VOLUME ["/app/output"]

# Run via shell so redirection works
CMD ["/bin/sh", "-c", "python -u snapshotd.py 2>&1 > /app/output/log.txt"]
