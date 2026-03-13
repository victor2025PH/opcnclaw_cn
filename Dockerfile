FROM python:3.11-slim

LABEL maintainer="OpenClaw Team"
LABEL description="OpenClaw AI Voice Assistant v3.0 — Cloud-First"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p data models logs ssl data/voice_clones data/mcp_servers

RUN python -c "\
from cryptography import x509; \
from cryptography.x509.oid import NameOID; \
from cryptography.hazmat.primitives import hashes, serialization; \
from cryptography.hazmat.primitives.asymmetric import rsa; \
import datetime, ipaddress; \
key = rsa.generate_private_key(public_exponent=65537, key_size=2048); \
subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')]); \
cert = (x509.CertificateBuilder() \
    .subject_name(subject).issuer_name(subject) \
    .public_key(key.public_key()) \
    .serial_number(x509.random_serial_number()) \
    .not_valid_before(datetime.datetime.utcnow()) \
    .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=3650)) \
    .add_extension(x509.SubjectAlternativeName([ \
        x509.DNSName('localhost'), \
        x509.IPAddress(ipaddress.IPv4Address('127.0.0.1')), \
    ]), critical=False) \
    .sign(key, hashes.SHA256())); \
open('ssl/cert.pem','wb').write(cert.public_bytes(serialization.Encoding.PEM)); \
open('ssl/key.pem','wb').write(key.private_bytes( \
    serialization.Encoding.PEM, \
    serialization.PrivateFormat.TraditionalOpenSSL, \
    serialization.NoEncryption()))" \
    || echo "SSL generation skipped"

EXPOSE 8765 8766

ENV OPENCLAW_HOST=0.0.0.0
ENV OPENCLAW_PORT=8765
ENV OPENCLAW_HTTP_PORT=8766

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import httpx; r=httpx.get('http://localhost:8766/api/health',timeout=3); exit(0 if r.status_code==200 else 1)" \
    || exit 1

CMD ["python", "launcher.py"]
