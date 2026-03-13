"""
Generate self-signed CA + server certificates for HTTPS LAN access.
Required for iOS Safari to allow getUserMedia (microphone/camera).
"""

import datetime
import ipaddress
import os
import socket
import sys
from pathlib import Path

from cryptography import x509
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def get_lan_ips():
    """Get all LAN IP addresses of this machine."""
    ips = set()
    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            ips.add(ip)
    except Exception:
        pass
    ips.add("127.0.0.1")
    return sorted(ips)


def generate_certs(cert_dir: str = "certs", force: bool = False):
    """Generate CA and server certificates."""
    cert_path = Path(cert_dir)
    cert_path.mkdir(exist_ok=True)

    ca_key_file = cert_path / "ca.key"
    ca_cert_file = cert_path / "ca.crt"
    server_key_file = cert_path / "server.key"
    server_cert_file = cert_path / "server.crt"

    if not force and ca_cert_file.exists() and server_cert_file.exists():
        print(f"Certificates already exist in {cert_dir}/")
        return str(ca_cert_file), str(server_cert_file), str(server_key_file)

    lan_ips = get_lan_ips()
    print(f"LAN IPs: {lan_ips}")

    # --- CA ---
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "OpenClaw Local CA"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "OpenClaw"),
    ])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, key_cert_sign=True, crl_sign=True,
                content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False,
                encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )

    ca_key_file.write_bytes(ca_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ))
    ca_cert_file.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    print(f"CA certificate: {ca_cert_file}")

    # --- Server cert signed by CA ---
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    san_list = [x509.DNSName("localhost")]
    for ip in lan_ips:
        try:
            san_list.append(x509.IPAddress(ipaddress.IPv4Address(ip)))
        except Exception:
            pass

    server_cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "OpenClaw Voice Server"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "OpenClaw"),
        ]))
        .issuer_name(ca_cert.subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=825))
        .add_extension(
            x509.SubjectAlternativeName(san_list),
            critical=False,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    server_key_file.write_bytes(server_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ))
    server_cert_file.write_bytes(server_cert.public_bytes(serialization.Encoding.PEM))
    print(f"Server certificate: {server_cert_file}")
    print(f"SANs: localhost, {', '.join(lan_ips)}")

    return str(ca_cert_file), str(server_cert_file), str(server_key_file)


if __name__ == "__main__":
    force = "--force" in sys.argv
    ca, cert, key = generate_certs(force=force)
    print(f"\nTo start with HTTPS:")
    print(f"  uvicorn src.server.main:app --host 0.0.0.0 --port 8765 --ssl-keyfile {key} --ssl-certfile {cert}")
