from pathlib import Path

from backup_agent.util import cleanup_parts, sha256_file, split_file


def test_split_and_cleanup(tmp_path: Path):
    source = tmp_path / "payload.bin"
    source.write_bytes(b"0123456789")

    parts = split_file(source, 4)
    assert [p.read_bytes() for p in parts] == [b"0123", b"4567", b"89"]
    assert b"".join(p.read_bytes() for p in parts) == source.read_bytes()

    cleanup_parts(parts, source)
    assert source.exists()
    assert all(not p.exists() for p in parts)


def test_sha256(tmp_path: Path):
    source = tmp_path / "hello.txt"
    source.write_bytes(b"hello")
    assert sha256_file(source) == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
