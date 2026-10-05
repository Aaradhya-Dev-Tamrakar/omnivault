"""
Tests for OmniVault Cloud Pack Archiving Engine
"""

from pathlib import Path

from omnivault.cloud_pack import (
    analyze_source_directory,
    build_pack_command,
    detect_archiver,
    register_cloud_archive_in_catalog,
    run_cloud_pack,
)
from omnivault.db import init_db, search


def test_analyze_source_directory(tmp_path: Path):
    sample_dir = tmp_path / "game_sample"
    sample_dir.mkdir()
    (sample_dir / "setup.exe").write_bytes(b"\x00" * 1024)
    (sample_dir / "data-01.bin").write_bytes(b"\x00" * (100 * 1024))  # 100 KB bin

    analysis = analyze_source_directory(sample_dir)
    assert analysis.total_files == 2
    assert analysis.is_precompressed is True
    assert analysis.recommended_mode == "store"
    assert analysis.staging_drive is not None


def test_detect_archiver():
    tool_type, tool_path = detect_archiver()
    assert tool_type in ("winrar", "7zip")
    assert Path(tool_path).exists()


def test_build_pack_command(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "test.bin").write_bytes(b"data")
    out = tmp_path / "out" / "pack.rar"

    tool_type, cmd = build_pack_command(
        source_path=source,
        output_archive=out,
        split_size="5g",
        parity_pct=5,
        password="secretpassword",
        store_mode=True,
    )
    assert tool_type in ("winrar", "7zip")
    assert any("5g" in c for c in cmd)
    assert any("-m0" in c or "-mx=0" in c for c in cmd)
    if tool_type == "winrar":
        assert any("-rr5%" in c for c in cmd)
        assert any("-hpsecretpassword" in c for c in cmd)


def test_register_and_search_cloud_archive(tmp_path: Path):
    db_file = tmp_path / "catalog.db"
    init_db(db_file)

    part1 = tmp_path / "test_archive.part01.rar"
    part2 = tmp_path / "test_archive.part02.rar"
    part1.write_bytes(b"chunk1")
    part2.write_bytes(b"chunk2")

    vol_id = register_cloud_archive_in_catalog(
        archive_name="Wukong_Game",
        cloud_provider="Google Drive",
        original_path="D:/Games/Black Myth Wukong",
        total_bytes=1000000,
        volume_parts=[part1, part2],
        db_path=db_file,
    )

    assert vol_id > 0

    # Search for original game name or archive
    res = search("Wukong", db_path=db_file)
    assert res["total"] >= 1
    filenames = [r["filename"] for r in res["items"]]
    assert any("Wukong" in fn for fn in filenames)


def test_run_cloud_pack_dry_run(tmp_path: Path):
    source = tmp_path / "test_pack_dir"
    source.mkdir()
    (source / "chunk.bin").write_bytes(b"binary data")

    res = run_cloud_pack(
        source_dir=source,
        split_size="10g",
        parity_pct=3,
        execute=False,
    )
    assert res["executed"] is False
    assert res["is_precompressed"] is True
    assert "command_str" in res
