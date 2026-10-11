import base64
import binascii
import os
from collections.abc import Mapping

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import BaseModel, ConfigDict, SecretStr

KEY_BYTES = 32
NONCE_BYTES = 12


class DecryptionError(Exception):
    """Ciphertext, nonce, key version or associated data do not match. Never carries secret data."""


class EncryptedSecret(BaseModel):
    model_config = ConfigDict(frozen=True)

    ciphertext: bytes
    nonce: bytes
    key_version: int


def secret_aad(*, table: str, row_id: str, user_id: str) -> bytes:
    # Binding to table/row/user stops ciphertext from decrypting after a copy to another row.
    return f"{table}:{row_id}:{user_id}".encode()


class SecretBox:
    """AES-256-GCM for stored credentials (ADR-0012). Old key versions stay decryptable."""

    def __init__(self, *, keys: Mapping[int, bytes], current_version: int) -> None:
        for version, key in keys.items():
            if len(key) != KEY_BYTES:
                raise ValueError(f"key version {version} must be 32 bytes")
        if current_version not in keys:
            raise ValueError("current_version has no key")
        self._ciphers = {version: AESGCM(key) for version, key in keys.items()}
        self.current_version = current_version

    @classmethod
    def from_base64(cls, encoded: str, *, version: int = 1) -> "SecretBox":
        try:
            key = base64.b64decode(encoded, validate=True)
        except binascii.Error as exc:
            raise ValueError("master key is not valid base64") from exc
        return cls(keys={version: key}, current_version=version)

    def encrypt(self, plaintext: str, *, aad: bytes) -> EncryptedSecret:
        nonce = os.urandom(NONCE_BYTES)
        cipher = self._ciphers[self.current_version]
        return EncryptedSecret(
            ciphertext=cipher.encrypt(nonce, plaintext.encode(), aad),
            nonce=nonce,
            key_version=self.current_version,
        )

    def decrypt(self, sealed: EncryptedSecret, *, aad: bytes) -> SecretStr:
        cipher = self._ciphers.get(sealed.key_version)
        if cipher is None:
            raise DecryptionError("unknown key version")
        try:
            plaintext = cipher.decrypt(sealed.nonce, sealed.ciphertext, aad)
        except InvalidTag as exc:
            raise DecryptionError("secret failed authentication") from exc
        return SecretStr(plaintext.decode())
