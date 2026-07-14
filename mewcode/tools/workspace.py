from __future__ import annotations

import asyncio
import heapq
import os
from collections.abc import AsyncIterator
from pathlib import Path, PurePath

import pathspec

from mewcode.cancellation import CancellationToken
from mewcode.errors import WorkspacePathError
from mewcode.tools.base import Deadline


class Workspace:
    def __init__(self, root: Path):
        self.root = root.resolve(strict=True)
        if not self.root.is_dir():
            raise WorkspacePathError(f"Workspace root is not a directory: {root}")
        ignore_file = self.root / ".gitignore"
        lines = ignore_file.read_text(encoding="utf-8").splitlines() if ignore_file.is_file() else []
        self._ignore_spec = pathspec.GitIgnoreSpec.from_lines(lines)

    def _relative_parts(self, raw_path: str) -> tuple[str, ...]:
        path = PurePath(raw_path)
        if not raw_path or path.is_absolute():
            raise WorkspacePathError("Tool paths must be non-empty workspace-relative paths.")
        if ".." in path.parts:
            raise WorkspacePathError("Parent path components ('..') are not allowed.")
        return path.parts

    def _ensure_within_root(self, path: Path) -> None:
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise WorkspacePathError("Path resolves outside the workspace.") from exc

    def resolve_existing(self, raw_path: str, *, require_file: bool = True) -> Path:
        parts = self._relative_parts(raw_path)
        try:
            candidate = (self.root.joinpath(*parts)).resolve(strict=True)
        except FileNotFoundError as exc:
            raise WorkspacePathError(
                f"Workspace path was not found: {raw_path}", code="not_found"
            ) from exc
        self._ensure_within_root(candidate)
        if require_file and not candidate.is_file():
            raise WorkspacePathError(f"Path is not a regular file: {raw_path}")
        return candidate

    def resolve_for_create(self, raw_path: str) -> Path:
        parts = self._relative_parts(raw_path)
        candidate = self.root.joinpath(*parts)
        current = self.root
        for part in parts[:-1]:
            current = current / part
            if current.exists() or current.is_symlink():
                resolved = current.resolve(strict=True)
                self._ensure_within_root(resolved)
                if not resolved.is_dir():
                    raise WorkspacePathError(f"Parent path is not a directory: {current}")
                current = resolved
        resolved_parent = candidate.parent.resolve(strict=False)
        self._ensure_within_root(resolved_parent)
        if candidate.exists() or candidate.is_symlink():
            resolved = candidate.resolve(strict=True)
            self._ensure_within_root(resolved)
            if resolved.is_dir():
                raise WorkspacePathError(f"Target path is a directory: {raw_path}")
            return resolved
        return resolved_parent / candidate.name

    def relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def is_ignored(self, relative_path: str, *, is_dir: bool = False) -> bool:
        normalized = relative_path.strip("/")
        if not normalized:
            return False
        if normalized == ".git" or normalized.startswith(".git/"):
            return True
        candidate = f"{normalized}/" if is_dir else normalized
        return self._ignore_spec.match_file(candidate)

    def _read_directory(self, directory: Path) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
        directories: list[Path] = []
        files: list[Path] = []
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    relative = self.relative(path)
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            if not self.is_ignored(relative, is_dir=True):
                                directories.append(path)
                        elif entry.is_file(follow_symlinks=False) and not self.is_ignored(
                            relative
                        ):
                            files.append(path)
                    except OSError:
                        continue
        except OSError:
            return (), ()

        return (
            tuple(sorted(directories, key=self.relative)),
            tuple(sorted(files, key=self.relative)),
        )

    async def walk_files(
        self,
        deadline: Deadline,
        cancellation: CancellationToken,
    ) -> AsyncIterator[Path]:
        pending: list[tuple[str, bool, Path]] = [("", True, self.root)]
        while pending:
            cancellation.raise_if_cancelled()
            deadline.check()
            _, is_directory, path = heapq.heappop(pending)
            if not is_directory:
                yield path
                continue

            directories, files = await asyncio.to_thread(self._read_directory, path)
            cancellation.raise_if_cancelled()
            deadline.check()
            for child in directories:
                heapq.heappush(pending, (f"{self.relative(child)}/", True, child))
            for child in files:
                heapq.heappush(pending, (self.relative(child), False, child))
