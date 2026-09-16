# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unsupported requested content must never become a passive-asset exclusion."""

import bz2
import io
import json
import tarfile
import zipfile
from pathlib import Path

import pytest

from skillspector.input_handler import InputHandler
from skillspector.mcp_server import run_scan

_SKILL = b"---\nname: primary-input-check\ndescription: Summarize supplied text.\n---\n# Notes\nSummarize the supplied text.\n"
_PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(32))


def _archive_bytes(*, compressed: bool = False) -> bytes:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz" if compressed else "w") as archive:
        member = tarfile.TarInfo("SKILL.md")
        member.size = len(_SKILL)
        archive.addfile(member, io.BytesIO(_SKILL))
    return stream.getvalue()


@pytest.mark.parametrize(
    ("name", "data", "directory"),
    [
        ("payload.dat", bytes([0x80, 0x81, 0x82, 0x83, 0, 0xFF]) * 20, False),
        ("SKILL.md", _SKILL.decode().encode("utf-16"), False),
        ("SKILL.md", _SKILL.decode().encode("utf-16"), True),
        ("skill.md", _SKILL.decode().encode("utf-16-be"), True),
        ("bundle.tar", _archive_bytes(), False),
        ("bundle.tar.gz", _archive_bytes(compressed=True), False),
        ("notes.md", _archive_bytes(), False),
        ("notes.md", _archive_bytes(compressed=True), False),
        ("notes.md", bz2.compress(_SKILL), False),
    ],
    ids=[
        "opaque-file",
        "utf16-file",
        "utf16-primary",
        "utf16-no-bom",
        "tar",
        "targz",
        "renamed-tar",
        "renamed-gzip",
        "renamed-bzip2",
    ],
)
async def test_unsupported_primary_is_incomplete_and_not_install_safe(
    tmp_path: Path, name: str, data: bytes, directory: bool
) -> None:
    target = tmp_path / name
    target.write_bytes(data)

    result = await run_scan(str(tmp_path if directory else target), use_llm=False)

    assert result["safe_to_install"] is False
    completeness = result["analysis_completeness"]
    assert completeness["is_complete"] is False
    assert completeness["total_components"] >= 1
    assert completeness["coverage_percent"] < 100.0
    assert result["recommendation"] != "SAFE"
    exceptions = completeness["ledger_exceptions"]
    assert any(
        item["path"] == name and item["reason_code"] == "unsupported_primary_content"
        for item in exceptions
    )
    assert not any(item["path"] == name for item in completeness["scope_exclusions"])


@pytest.mark.parametrize("referenced", [False, True])
async def test_passive_asset_keeps_existing_reference_policy(
    tmp_path: Path, referenced: bool
) -> None:
    instructions = _SKILL + (b"\nRead [image](image.png).\n" if referenced else b"")
    (tmp_path / "SKILL.md").write_bytes(instructions)
    (tmp_path / "image.png").write_bytes(_PNG)

    result = await run_scan(str(tmp_path), use_llm=False)

    assert result["analysis_completeness"]["is_complete"] is not referenced
    assert result["safe_to_install"] is not referenced
    assert not any(
        item["reason_code"] == "unsupported_primary_content"
        for item in result["analysis_completeness"]["ledger_exceptions"]
    )
    if not referenced:
        assert any(
            item["path"] == "image.png" and item["reason_code"] == "binary_content"
            for item in result["analysis_completeness"]["scope_exclusions"]
        )


@pytest.mark.parametrize("layout", ["flat", "nested", "empty", "renamed"])
async def test_supported_zip_remains_complete(tmp_path: Path, layout: str) -> None:
    target = tmp_path / ("bundle.dat" if layout == "renamed" else "bundle.zip")
    with zipfile.ZipFile(target, "w") as archive:
        if layout != "empty":
            archive.writestr("skill/SKILL.md" if layout == "nested" else "SKILL.md", _SKILL)
            archive.writestr("skill/image.png" if layout == "nested" else "image.png", _PNG)

    result = await run_scan(str(target), use_llm=False)

    assert result["analysis_completeness"]["is_complete"] is True
    assert result["safe_to_install"] is True


async def test_explicit_text_with_binary_extension_preserves_source_path(tmp_path: Path) -> None:
    target = tmp_path / "instructions.png"
    target.write_bytes(_SKILL)

    result = await run_scan(str(target), use_llm=False)

    assert result["analysis_completeness"]["is_complete"] is True
    payload = json.loads(result["report"])
    assert payload["analysis_completeness"]["fully_inspected_files"] == 1


@pytest.mark.parametrize(
    "text",
    [
        b"BZh is the bzip2 file prefix. Summarize the supplied document.",
        b"BZh9 is a bzip2 header. Summarize the supplied document.",
        b"# Notes\n" + b" " * 249 + b"ustar denotes the TAR format.\n",
    ],
)
async def test_archive_magic_words_remain_analyzable_text(tmp_path: Path, text: bytes) -> None:
    target = tmp_path / "notes.md"
    target.write_bytes(text)

    result = await run_scan(str(target), use_llm=False)

    assert result["safe_to_install"] is True
    assert result["analysis_completeness"]["is_complete"] is True
    assert result["analysis_completeness"]["fully_inspected_files"] == 1
    assert not result["analysis_completeness"]["ledger_exceptions"]


@pytest.mark.parametrize("archive", [False, True])
async def test_downloaded_file_keeps_primary_identity_but_zip_members_are_passive(
    monkeypatch: pytest.MonkeyPatch, archive: bool
) -> None:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as bundle:
        bundle.writestr("SKILL.md", _SKILL)
        bundle.writestr("image.png", _PNG)
    content = stream.getvalue() if archive else _PNG
    headers = {"content-type": "application/zip" if archive else "application/octet-stream"}
    target = "https://raw.githubusercontent.com/example/skill/main/notes.md"
    monkeypatch.setattr(
        InputHandler,
        "_download_with_redirect_validation",
        lambda _self, _url: (headers, target, content),
    )

    result = await run_scan(target, use_llm=False)

    assert result["analysis_completeness"]["is_complete"] is archive
    assert result["safe_to_install"] is archive
    if not archive:
        assert any(
            item["path"] == "notes.md" and item["reason_code"] == "unsupported_primary_content"
            for item in result["analysis_completeness"]["ledger_exceptions"]
        )
