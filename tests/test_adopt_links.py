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


def test_a_destination_with_a_space_follows_the_move(tmp_path):
    root = tmp_path / "r"
    write(root / "PROGRESS.md", "[문서](my file.md)\n")

    changed = notes_adopt.rewrite_links(root, [("my file.md", "docs/my file.md")])

    assert changed == 1
    text = (root / "PROGRESS.md").read_text(encoding="utf-8")
    assert "(docs/my file.md)" in text


def test_an_angle_bracket_destination_follows_and_keeps_the_brackets(tmp_path):
    root = tmp_path / "r"
    write(root / "PROGRESS.md", "[문서](<my file.md>)\n")

    notes_adopt.rewrite_links(root, [("my file.md", "docs/my file.md")])

    text = (root / "PROGRESS.md").read_text(encoding="utf-8")
    assert "(<docs/my file.md>)" in text


def test_a_destination_with_one_level_of_parens_follows_the_move(tmp_path):
    root = tmp_path / "r"
    write(root / "PROGRESS.md", "[문서](file(1).md)\n")

    notes_adopt.rewrite_links(root, [("file(1).md", "docs/file(1).md")])

    text = (root / "PROGRESS.md").read_text(encoding="utf-8")
    assert "(docs/file(1).md)" in text


def test_a_parenthesized_name_that_exists_is_not_reported_broken(tmp_path):
    root = tmp_path / "r"
    write(root / "PROGRESS.md", "[문서](file(1).md)\n")
    write(root / "file(1).md", "# x\n")

    assert notes_adopt.broken_links(root) == []


def test_an_html_image_src_follows_the_move(tmp_path):
    root = tmp_path / "r"
    write(root / "PROGRESS.md", '<img src="old/그림.png">\n')

    changed = notes_adopt.rewrite_links(root, [("old/그림.png", "docs/그림.png")])

    assert changed == 1
    text = (root / "PROGRESS.md").read_text(encoding="utf-8")
    assert 'src="docs/그림.png"' in text


def test_an_html_link_href_with_single_quotes_follows_the_move(tmp_path):
    root = tmp_path / "r"
    write(root / "PROGRESS.md", "<a href='old/문서.md'>글</a>\n")

    changed = notes_adopt.rewrite_links(root, [("old/문서.md", "docs/문서.md")])

    assert changed == 1
    text = (root / "PROGRESS.md").read_text(encoding="utf-8")
    assert "href='docs/문서.md'" in text


def test_html_inside_a_code_block_is_left_alone(tmp_path):
    root = tmp_path / "r"
    write(root / "PROGRESS.md", '```\n<img src="old/그림.png">\n```\n')

    changed = notes_adopt.rewrite_links(root, [("old/그림.png", "docs/그림.png")])

    assert changed == 0
    assert '<img src="old/그림.png">' in (root / "PROGRESS.md").read_text(encoding="utf-8")
