import base64
import os

import pytest

from querycure.core.crypto import DecryptionError, SecretBox, secret_aad


def make_box(version: int = 1) -> SecretBox:
    return SecretBox(keys={version: os.urandom(32)}, current_version=version)


def test_round_trip_returns_original_secret() -> None:
    box = make_box()
    aad = secret_aad(table="llm_credentials", row_id="r1", user_id="u1")

    sealed = box.encrypt("sk-or-v1-abc", aad=aad)

    assert box.decrypt(sealed, aad=aad).get_secret_value() == "sk-or-v1-abc"
    assert sealed.key_version == 1
    assert len(sealed.nonce) == 12
    assert b"sk-or-v1-abc" not in sealed.ciphertext


def test_same_plaintext_encrypts_differently_each_time() -> None:
    box = make_box()
    aad = secret_aad(table="t", row_id="r", user_id="u")

    first, second = box.encrypt("same", aad=aad), box.encrypt("same", aad=aad)

    assert first.nonce != second.nonce
    assert first.ciphertext != second.ciphertext


def test_tampered_ciphertext_is_rejected() -> None:
    box = make_box()
    aad = secret_aad(table="t", row_id="r", user_id="u")
    sealed = box.encrypt("secret", aad=aad)
    flipped = bytes([sealed.ciphertext[0] ^ 0x01]) + sealed.ciphertext[1:]

    with pytest.raises(DecryptionError):
        box.decrypt(sealed.model_copy(update={"ciphertext": flipped}), aad=aad)


def test_ciphertext_cannot_be_moved_to_another_row_or_user() -> None:
    box = make_box()
    sealed = box.encrypt("secret", aad=secret_aad(table="t", row_id="r1", user_id="u1"))

    with pytest.raises(DecryptionError):
        box.decrypt(sealed, aad=secret_aad(table="t", row_id="r2", user_id="u1"))
    with pytest.raises(DecryptionError):
        box.decrypt(sealed, aad=secret_aad(table="t", row_id="r1", user_id="u2"))


def test_old_key_version_still_decrypts_after_rotation() -> None:
    old_key, new_key = os.urandom(32), os.urandom(32)
    aad = secret_aad(table="t", row_id="r", user_id="u")
    sealed = SecretBox(keys={1: old_key}, current_version=1).encrypt("secret", aad=aad)

    rotated = SecretBox(keys={1: old_key, 2: new_key}, current_version=2)

    assert rotated.decrypt(sealed, aad=aad).get_secret_value() == "secret"
    assert rotated.encrypt("secret", aad=aad).key_version == 2


def test_unknown_key_version_is_rejected() -> None:
    aad = secret_aad(table="t", row_id="r", user_id="u")
    sealed = make_box(version=1).encrypt("secret", aad=aad)

    with pytest.raises(DecryptionError):
        make_box(version=2).decrypt(sealed, aad=aad)


@pytest.mark.parametrize("size", [0, 16, 31, 33])
def test_keys_must_be_32_bytes(size: int) -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        SecretBox(keys={1: os.urandom(size)}, current_version=1)


def test_current_version_must_exist() -> None:
    with pytest.raises(ValueError, match="current_version"):
        SecretBox(keys={1: os.urandom(32)}, current_version=2)


def test_from_base64_key() -> None:
    raw = os.urandom(32)

    box = SecretBox.from_base64(base64.b64encode(raw).decode(), version=3)

    assert box.current_version == 3


def test_a_restore_with_another_master_key_fails_closed() -> None:
    """DEPLOYMENT §4c: a backup restored without the master key that sealed it (same key
    version, different key bytes) must raise, never return plaintext or garbage."""
    aad = secret_aad(table="llm_credentials", row_id="r1", user_id="u1")
    sealed = make_box().encrypt("sk-or-v1-abc", aad=aad)

    with pytest.raises(DecryptionError):
        make_box().decrypt(sealed, aad=aad)
