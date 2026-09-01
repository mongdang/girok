"""Keeping references pointing at documents that moved.

Files surviving is what the backup guarantees. Links surviving is not — a
document can be intact at its new path while every reference to it is dead,
and no hash check notices that.
"""
import notes_adopt

from conftest import write


def test_a_relative_link_follows_the_move(tmp_path):
    root = tmp_path / "r"
    write(root / "PROGRESS.md", "본문 [결정](decisions/001-first.md) 참고\n")

    changed = notes_adopt.rewrite_links(
        root, [("decisions/001-first.md", "docs/decisions/ADR-001-first.md")]
    )

    assert changed == 1
    text = (root / "PROGRESS.md").read_text(encoding="utf-8")
    assert "(docs/decisions/ADR-001-first.md)" in text


def test_an_anchor_is_kept(tmp_path):
    root = tmp_path / "r"
    write(root / "PROGRESS.md", "[결정](decisions/001-first.md#결정)\n")

    notes_adopt.rewrite_links(
        root, [("decisions/001-first.md", "docs/decisions/ADR-001-first.md")]
    )

    text = (root / "PROGRESS.md").read_text(encoding="utf-8")
    assert "(docs/decisions/ADR-001-first.md#결정)" in text


def test_an_image_follows_too(tmp_path):
    root = tmp_path / "r"
    write(root / "설계.md", "![그림](old/도면.md)\n")

    notes_adopt.rewrite_links(root, [("old/도면.md", "docs/도면.md")])

    text = (root / "설계.md").read_text(encoding="utf-8")
    assert "(docs/도면.md)" in text


def test_a_reference_style_link_follows(tmp_path):
    root = tmp_path / "r"
    write(root / "PROGRESS.md", "[결정]: decisions/001-first.md\n")

    notes_adopt.rewrite_links(
        root, [("decisions/001-first.md", "docs/decisions/ADR-001-first.md")]
    )

    text = (root / "PROGRESS.md").read_text(encoding="utf-8")
    assert "docs/decisions/ADR-001-first.md" in text


def test_a_path_inside_a_code_block_is_left_alone(tmp_path):
    root = tmp_path / "r"
    write(root / "PROGRESS.md", "```\ncat decisions/001-first.md\n```\n")

    changed = notes_adopt.rewrite_links(
        root, [("decisions/001-first.md", "docs/decisions/ADR-001-first.md")]
    )

    assert changed == 0
    assert "cat decisions/001-first.md" in (root / "PROGRESS.md").read_text(encoding="utf-8")


def test_an_external_url_is_left_alone(tmp_path):
    root = tmp_path / "r"
    write(root / "PROGRESS.md", "[집](https://example.invalid/decisions/001-first.md)\n")

    changed = notes_adopt.rewrite_links(
        root, [("decisions/001-first.md", "docs/decisions/ADR-001-first.md")]
    )

    assert changed == 0


def test_broken_links_are_reported(tmp_path):
    root = tmp_path / "r"
    write(root / "PROGRESS.md", "[없다](docs/없는문서.md)\n")

    assert notes_adopt.broken_links(root) == [("PROGRESS.md", "docs/없는문서.md")]


def test_a_link_that_resolves_is_not_reported(tmp_path):
    root = tmp_path / "r"
    write(root / "PROGRESS.md", "[있다](docs/있다.md)\n")
    write(root / "docs" / "있다.md", "# 있다\n")

    assert notes_adopt.broken_links(root) == []
