import pytest

from app.core.security import (
    hash_password,
    keep_stored_password,
    mask_rtsp_url,
    redact,
    verify_password,
)


def test_password_hash_roundtrip() -> None:
    stored = hash_password("a long passphrase")
    assert stored.startswith("scrypt$")
    assert "a long passphrase" not in stored
    assert verify_password("a long passphrase", stored)
    assert not verify_password("wrong", stored)
    assert not verify_password("a long passphrase", "garbage")
    assert hash_password("same") != hash_password("same")  # random salt


def test_mask_rtsp_url() -> None:
    assert (
        mask_rtsp_url("rtsp://admin:s3cret@10.0.0.9:554/live")
        == "rtsp://admin:***@10.0.0.9:554/live"
    )
    assert mask_rtsp_url("rtsp://10.0.0.9/live") == "rtsp://10.0.0.9/live"
    assert mask_rtsp_url("rtsp://user@10.0.0.9/live") == "rtsp://user@10.0.0.9/live"
    # passwords containing @ are still hidden completely
    assert mask_rtsp_url("rtsp://u:p@ss@host/x") == "rtsp://u:***@host/x"


def test_masked_url_keeps_stored_password() -> None:
    stored = "rtsp://admin:s3cret@10.0.0.9/live"
    assert keep_stored_password("rtsp://admin:***@10.0.0.20/live", stored) == (
        "rtsp://admin:s3cret@10.0.0.20/live"
    )
    assert keep_stored_password("rtsp://admin:new@10.0.0.9/live", stored) == (
        "rtsp://admin:new@10.0.0.9/live"
    )
    with pytest.raises(ValueError):
        keep_stored_password("rtsp://admin:***@h/x", "rtsp://h/x")


def test_redact_free_text() -> None:
    text = "[rtsp @ 0x1] rtsp://admin:s3cret@10.0.0.9:554/live: Connection refused"
    assert "s3cret" not in redact(text)
    assert "rtsp://admin:***@10.0.0.9:554/live" in redact(text)
    assert redact("no urls here") == "no urls here"
    # ffmpeg splits user info at the LAST @: a password containing @ is masked completely
    leaked = redact("rtsp://admin:p@ss@cam/stream: Connection refused")
    assert leaked == "rtsp://admin:***@cam/stream: Connection refused"
