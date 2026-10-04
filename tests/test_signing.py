from controller.signing import (
    generate_keypair,
    load_private_key,
    load_public_key,
    sign_bytes,
    verify_bytes,
)


def test_ed25519_sign_and_verify(tmp_path):
    private_key_path = tmp_path / "private.pem"
    public_key_path = tmp_path / "public.pem"

    generate_keypair(
        private_key_path,
        public_key_path,
    )

    private_key = load_private_key(private_key_path)
    public_key = load_public_key(public_key_path)

    content = b"version: 1.6\nrules:\n  - name: test\n    action: allow\n"

    signature = sign_bytes(
        content,
        private_key,
    )

    assert verify_bytes(
        content,
        signature,
        public_key,
    )


def test_tampered_content_fails_verification(tmp_path):
    private_key_path = tmp_path / "private.pem"
    public_key_path = tmp_path / "public.pem"

    generate_keypair(
        private_key_path,
        public_key_path,
    )

    private_key = load_private_key(private_key_path)
    public_key = load_public_key(public_key_path)

    content = b"version: 1.6\nrules:\n  - name: test\n    action: allow\n"

    signature = sign_bytes(
        content,
        private_key,
    )

    assert not verify_bytes(
        content + b"tampered",
        signature,
        public_key,
    )


def test_wrong_public_key_fails_verification(tmp_path):
    private_key_path = tmp_path / "private.pem"
    public_key_path = tmp_path / "public.pem"

    wrong_private_key_path = tmp_path / "wrong-private.pem"
    wrong_public_key_path = tmp_path / "wrong-public.pem"

    generate_keypair(
        private_key_path,
        public_key_path,
    )

    generate_keypair(
        wrong_private_key_path,
        wrong_public_key_path,
    )

    private_key = load_private_key(private_key_path)
    wrong_public_key = load_public_key(
        wrong_public_key_path
    )

    content = b"version: 1.6\nrules:\n  - name: test\n    action: allow\n"

    signature = sign_bytes(
        content,
        private_key,
    )

    assert not verify_bytes(
        content,
        signature,
        wrong_public_key,
    )


def test_malformed_signature_fails_verification(tmp_path):
    private_key_path = tmp_path / "private.pem"
    public_key_path = tmp_path / "public.pem"

    generate_keypair(
        private_key_path,
        public_key_path,
    )

    private_key = load_private_key(private_key_path)
    public_key = load_public_key(public_key_path)

    content = b"version: 1.6\nrules:\n  - name: test\n    action: allow\n"

    signature = sign_bytes(
        content,
        private_key,
    )

    malformed_signature = signature[:-4] + "!!!!"

    assert not verify_bytes(
        content,
        malformed_signature,
        public_key,
    )
