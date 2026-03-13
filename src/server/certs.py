"""Auto-generate HTTPS certificates for LAN access (required for iOS mic/camera)."""

import base64
import datetime
import ipaddress
import socket
import uuid
from pathlib import Path

from cryptography import x509
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from loguru import logger


def get_lan_ips():
    """Get all LAN IPv4 addresses of this machine."""
    ips = set()
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ips.add(info[4][0])
    except Exception:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ips.add(s.getsockname()[0])
    except Exception:
        pass
    ips.add("127.0.0.1")
    return sorted(ips)


def ensure_certs(cert_dir: str = "certs") -> tuple[str, str, str]:
    """Generate CA + server certificates if not present.

    Returns (ca_crt_path, server_crt_path, server_key_path).
    """
    cert_path = Path(cert_dir)
    ca_crt = cert_path / "ca.crt"
    server_crt = cert_path / "server.crt"
    server_key = cert_path / "server.key"

    if ca_crt.exists() and server_crt.exists() and server_key.exists():
        logger.info(f"Using existing certificates in {cert_dir}/")
        return str(ca_crt), str(server_crt), str(server_key)

    cert_path.mkdir(exist_ok=True)
    lan_ips = get_lan_ips()
    logger.info(f"Generating HTTPS certificates for LAN IPs: {lan_ips}")

    # ── CA ──
    ca_private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "OpenClaw Local CA"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "OpenClaw"),
    ])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_private.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=True, key_cert_sign=True, crl_sign=True,
            content_commitment=False, key_encipherment=False,
            data_encipherment=False, key_agreement=False,
            encipher_only=False, decipher_only=False,
        ), critical=True)
        .sign(ca_private, hashes.SHA256())
    )

    (cert_path / "ca.key").write_bytes(ca_private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ))
    ca_crt.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))

    # ── Server cert signed by CA ──
    srv_private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    san_list = [x509.DNSName("localhost")]
    for ip in lan_ips:
        try:
            san_list.append(x509.IPAddress(ipaddress.IPv4Address(ip)))
        except Exception:
            pass

    srv_cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "OpenClaw Voice Server"),
        ]))
        .issuer_name(ca_cert.subject)
        .public_key(srv_private.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(san_list), critical=False)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(ca_private, hashes.SHA256())
    )

    server_key.write_bytes(srv_private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ))
    server_crt.write_bytes(srv_cert.public_bytes(serialization.Encoding.PEM))

    logger.info(f"Certificates generated → {cert_dir}/  (SANs: localhost, {', '.join(lan_ips)})")
    return str(ca_crt), str(server_crt), str(server_key)


def generate_mobileconfig(ca_crt_path: str) -> str:
    """Generate an iOS .mobileconfig profile containing the CA certificate."""
    from cryptography.x509 import load_pem_x509_certificate

    pem_data = Path(ca_crt_path).read_bytes()
    cert = load_pem_x509_certificate(pem_data)
    der_b64 = base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode()

    profile_uuid = str(uuid.uuid4()).upper()
    payload_uuid = str(uuid.uuid4()).upper()

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>PayloadContent</key>
	<array>
		<dict>
			<key>PayloadCertificateFileName</key>
			<string>OpenClaw-CA.cer</string>
			<key>PayloadContent</key>
			<data>{der_b64}</data>
			<key>PayloadDescription</key>
			<string>Enables secure voice, camera, and gesture features over your local network.</string>
			<key>PayloadDisplayName</key>
			<string>OpenClaw Local CA</string>
			<key>PayloadIdentifier</key>
			<string>com.openclaw.ca.{payload_uuid}</string>
			<key>PayloadType</key>
			<string>com.apple.security.root</string>
			<key>PayloadUUID</key>
			<string>{payload_uuid}</string>
			<key>PayloadVersion</key>
			<integer>1</integer>
		</dict>
	</array>
	<key>PayloadDisplayName</key>
	<string>OpenClaw AI - Secure Connection</string>
	<key>PayloadDescription</key>
	<string>Install this profile to use OpenClaw AI voice, camera, and gesture features from your iPhone/iPad.</string>
	<key>PayloadIdentifier</key>
	<string>com.openclaw.profile.{profile_uuid}</string>
	<key>PayloadRemovalDisallowed</key>
	<false/>
	<key>PayloadType</key>
	<string>Configuration</string>
	<key>PayloadUUID</key>
	<string>{profile_uuid}</string>
	<key>PayloadVersion</key>
	<integer>1</integer>
</dict>
</plist>"""
