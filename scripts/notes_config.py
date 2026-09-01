"""Reading `<repo>/.claude/girok.json`.

Everything project-specific in this methodology lives in that one file, so
the skills and scripts stay general. The file is optional: an agent that
clones a repository without the plugin still has to be able to run the
linter, so absent config falls back to looking for a folder that contains
`docs/`.

The layout keys exist because the second repository to adopt this had a
different one — `STATE.md` and `decisions/NNN-slug.md` at the root instead
of `docs/PROGRESS.md` and `docs/decisions/ADR-NNN-slug.md`. Renaming its
52 decision files would have cost more than it returned, and a methodology
that only fits the repository it was extracted from is a copy with extra
steps.

`pluginConfigs` cannot be used for this — its settings scope is
user-or-managed, so a value committed to a repository is ignored.
"""
import json
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_RELATIVE = Path(".claude") / "girok.json"
# The plugin's pre-rename config name. Repositories that adopted before the
# rename still carry it; refusing to read it would turn a rename into a
# breaking change for every one of them.
LEGACY_CONFIG_RELATIVE = Path(".claude") / "notes-method.json"


def _config_path(root: Path) -> Path | None:
    for rel in (CONFIG_RELATIVE, LEGACY_CONFIG_RELATIVE):
        if (root / rel).is_file():
            return root / rel
    return None

# tocMin is the size below which a document is not asked for a table of
# contents. Repositories with their own size caps (an 8KB board, say) get to
# raise it so the warning does not nag documents their rules call small.
DEFAULT_LIMITS_KB = {"rules": 20, "board": 30, "tocMin": 1.5}
DEFAULT_BOARD = "PROGRESS.md"
DEFAULT_DECISIONS_DIR = "docs/decisions"
DEFAULT_DOC_ROOTS = ("docs",)
DEFAULT_ROOT_DOCS = ("CLAUDE.md", "RULES.md")
DEFAULT_RULES_DOCS = ("CLAUDE.md", "RULES.md")

# How decision files are named and cited.
#
# "adr-prefixed"  ADR-NNN-slug.md / ADR-YYMMDD-<worker>-slug.md, cited ADR-NNN
# "numbered"      NNN-slug.md, cited `decisions/NNN` or `ADR-NNN`
#
# Bare numbers are deliberately not citations under "numbered": every figure
# in the prose would look like one, and the false positives would bury the
# real findings.
ADR_STYLES = ("adr-prefixed", "numbered")


@dataclass
class NotesConfig:
    repo_root: Path
    notes_dir: Path
    workers: dict = field(default_factory=dict)
    merge_owner: str | None = None
    modules: dict = field(default_factory=dict)
    limits_kb: dict = field(default_factory=lambda: dict(DEFAULT_LIMITS_KB))
    parallel_mode: bool = True
    read_only_repos: list = field(default_factory=list)
    source: Path | None = None
    board: str = DEFAULT_BOARD
    decisions_relative: str = DEFAULT_DECISIONS_DIR
    doc_roots_relative: tuple = DEFAULT_DOC_ROOTS
    root_docs: tuple = DEFAULT_ROOT_DOCS
    rules_docs: tuple = DEFAULT_RULES_DOCS
    adr_style: str = "adr-prefixed"
    is_repository: bool = True
    remote: str = "origin"
    # Folders the linter leaves alone, beyond the built-in archive/screenshots:
    # frozen process artifacts (plan transcripts, imported histories) that
    # predate the rules and are not going to be reformatted.
    skip_dirs: tuple = ()

    @property
    def docs_dir(self) -> Path:
        """The first configured doc root — where the board and gate live."""
        return self.notes_dir / self.doc_roots_relative[0]

    @property
    def decisions_dir(self) -> Path:
        return self.notes_dir / self.decisions_relative

    def doc_roots(self) -> list[Path]:
        return [self.notes_dir / rel for rel in self.doc_roots_relative]

    def board_paths(self) -> list[Path]:
        """Everywhere the board can be, main copy first.

        A layout may keep it at the notes root (`STATE.md`) or under a doc
        root (`docs/PROGRESS.md`), and parallel work adds one per worker.
        """
        found = [self.notes_dir / self.board]
        found.extend(root / self.board for root in self.doc_roots())
        found.extend(w / self.board for w in self.worker_dirs())
        return found

    def worker_dirs(self) -> list[Path]:
        if not self.parallel_mode:
            return []
        return sorted(p for p in self.notes_dir.glob("docs_*") if p.is_dir())

    def size_limit_bytes(self, name: str) -> int | None:
        """Byte budget for a document read in full every session.

        Korean text is three bytes per character in UTF-8, so counting
        characters understates the real context cost — count bytes.
        """
        if name == self.board:
            return self.limits_kb.get("board", DEFAULT_LIMITS_KB["board"]) * 1000
        if name in self.rules_docs:
            return self.limits_kb.get("rules", DEFAULT_LIMITS_KB["rules"]) * 1000
        return None


def find_repo_root(start: Path) -> Path:
    """Walk up looking for the config, then for a git repository."""
    start = start.resolve()
    for candidate in [start, *start.parents]:
        if _config_path(candidate) is not None:
            return candidate
    for candidate in [start, *start.parents]:
        if (candidate / ".git").exists():
            return candidate
    return start


def _is_repository(root: Path) -> bool:
    """A repository, as opposed to a directory that merely contains some.

    Claude Code has no repository picker — the folder it was started in is
    the subject — so being started one level too high is an ordinary mistake
    with a bad outcome, and it has to be recognized rather than guessed
    around.
    """
    return _config_path(root) is not None or (root / ".git").exists()


# Files that mark a folder as a project in its own right. Used only to
# recognize a *parent* of several projects — never to require one, because a
# records repository has no manifest and rejecting those was the bug this
# replaced.
MANIFESTS = (
    "pyproject.toml", "package.json", "go.mod", "Cargo.toml",
    "pom.xml", "build.gradle", "Gemfile", "composer.json",
)

# Folders that hold other people's checkouts rather than parts of this one.
_NOT_A_SIBLING = {".git", "node_modules", ".venv", "vendor", "packages", "third_party"}


def is_workspace(root: Path) -> bool:
    """A directory that merely *contains* projects, rather than being one.

    `git init` here would swallow every repository underneath into a single
    one, which is worse to undo than anything else adoption does. Two
    children that each look like a project is the signal; one is not, since
    a vendored dependency is an ordinary thing to find inside a project.
    """
    if not root.is_dir():
        return False
    projects = 0
    for child in sorted(p for p in root.iterdir() if p.is_dir()):
        if child.name in _NOT_A_SIBLING or child.name.startswith("."):
            continue
        if (child / ".git").exists() or any((child / m).is_file() for m in MANIFESTS):
            projects += 1
    return projects >= 2


def _guess_notes_dir(repo_root: Path) -> Path:
    """No config: find the folder holding `docs/`.

    Prefer the repository root itself, then a single level down, so both
    `<repo>/docs` and `<repo>/notes/docs` are recognized. A subfolder that is
    itself a repository is never adopted: in a directory holding several
    checkouts that would silently pick a different project's documents.
    """
    if (repo_root / "docs").is_dir():
        return repo_root
    candidates = sorted(
        p.parent
        for p in repo_root.glob("*/docs")
        if p.is_dir()
        and not p.parent.name.startswith(".")
        and not _is_repository(p.parent)
    )
    return candidates[0] if candidates else repo_root


def load(start: Path | str = ".") -> NotesConfig:
    repo_root = find_repo_root(Path(start))
    config_path = _config_path(repo_root)

    if config_path is None:
        return NotesConfig(
            repo_root=repo_root,
            notes_dir=_guess_notes_dir(repo_root),
            is_repository=_is_repository(repo_root),
        )

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    notes_dir = repo_root / raw.get("notesDir", ".")
    limits = raw.get("limits", {})

    adr_style = raw.get("adrStyle", "adr-prefixed")
    if adr_style not in ADR_STYLES:
        raise ValueError(
            f"adrStyle 이 {adr_style} — {' 또는 '.join(ADR_STYLES)} 중 하나여야 한다"
        )

    return NotesConfig(
        repo_root=repo_root,
        notes_dir=notes_dir,
        workers=raw.get("workers", {}),
        merge_owner=raw.get("mergeOwner"),
        modules=raw.get("modules", {}),
        limits_kb={
            "rules": limits.get("rulesKB", DEFAULT_LIMITS_KB["rules"]),
            "board": limits.get("boardKB", DEFAULT_LIMITS_KB["board"]),
            "tocMin": limits.get("tocMinKB", DEFAULT_LIMITS_KB["tocMin"]),
        },
        parallel_mode=raw.get("parallelMode", True),
        read_only_repos=raw.get("readOnlyRepos", []),
        source=config_path,
        board=raw.get("board") or DEFAULT_BOARD,
        decisions_relative=raw.get("decisionsDir") or DEFAULT_DECISIONS_DIR,
        # `or` rather than a default argument: a key present but empty (`[]`,
        # `null`) is a config someone half-edited, and an empty docRoots left
        # `docs_dir` indexing an empty tuple — every check died on it.
        doc_roots_relative=tuple(raw.get("docRoots") or DEFAULT_DOC_ROOTS),
        root_docs=tuple(raw.get("rootDocs") or DEFAULT_ROOT_DOCS),
        rules_docs=tuple(raw.get("rulesDocs") or DEFAULT_RULES_DOCS),
        adr_style=adr_style,
        remote=raw.get("remote") or "origin",
        skip_dirs=tuple(raw.get("skipDirs", [])),
    )
