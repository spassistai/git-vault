"""Local .git-vault workspace marker."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class WorkspaceError(Exception):
    pass


@dataclass
class Workspace:
    root: Path
    repo_id: str
    remote: str
    last_seq: int

    @property
    def marker(self) -> Path:
        return self.root / ".git-vault"

    def save(self) -> None:
        self.marker.mkdir(parents=True, exist_ok=True)
        (self.marker / "repo_id").write_text(self.repo_id + "\n", encoding="utf-8")
        (self.marker / "remote").write_text(self.remote + "\n", encoding="utf-8")
        (self.marker / "last_seq").write_text(str(self.last_seq) + "\n", encoding="utf-8")

    def set_last_seq(self, seq: int) -> None:
        self.last_seq = seq
        (self.marker / "last_seq").write_text(str(seq) + "\n", encoding="utf-8")


def find_workspace(start: Path | None = None) -> Workspace:
    cur = (start or Path.cwd()).resolve()
    for path in [cur, *cur.parents]:
        marker = path / ".git-vault"
        if marker.is_dir() and (marker / "repo_id").is_file():
            return load_workspace(path)
    raise WorkspaceError("not a git-vault working tree (missing .git-vault/)")


def load_workspace(root: Path) -> Workspace:
    marker = root / ".git-vault"
    try:
        repo_id = (marker / "repo_id").read_text(encoding="utf-8").strip()
        remote = (marker / "remote").read_text(encoding="utf-8").strip()
        last_seq_raw = (marker / "last_seq").read_text(encoding="utf-8").strip()
        last_seq = int(last_seq_raw) if last_seq_raw else 0
    except (OSError, ValueError) as exc:
        raise WorkspaceError(f"corrupt .git-vault marker in {root}") from exc
    if not repo_id or not remote:
        raise WorkspaceError(f"incomplete .git-vault marker in {root}")
    return Workspace(root=root, repo_id=repo_id, remote=remote, last_seq=last_seq)


def write_workspace(root: Path, repo_id: str, remote: str, last_seq: int = 0) -> Workspace:
    ws = Workspace(root=root, repo_id=repo_id, remote=remote, last_seq=last_seq)
    ws.save()
    return ws
