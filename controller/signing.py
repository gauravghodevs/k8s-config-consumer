import base64
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)


def generate_keypair(private_key_path, public_key_path):
    private_key = Ed25519PrivateKey.generate()

    public_key = private_key.public_key()

    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    public_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    private_path = Path(private_key_path)
    public_path = Path(public_key_path)

    private_path.parent.mkdir(parents=True, exist_ok=True)
    public_path.parent.mkdir(parents=True, exist_ok=True)

    private_path.write_bytes(private_bytes)
    public_path.write_bytes(public_bytes)

    private_path.chmod(0o600)
    public_path.chmod(0o644)


def load_private_key(path):
    return serialization.load_pem_private_key(
        Path(path).read_bytes(),
        password=None,
    )


def load_public_key(path):
    return serialization.load_pem_public_key(
        Path(path).read_bytes()
    )


def sign_bytes(content, private_key):
    signature = private_key.sign(content)

    return base64.b64encode(signature).decode("ascii")


def verify_bytes(content, signature, public_key):
    try:
        public_key.verify(
            base64.b64decode(signature),
            content,
        )
        return True
    except (InvalidSignature, ValueError):
        return False
