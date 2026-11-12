"""출력 폴더 준비. 이전 실행의 생성물이 남아 다시 올라가는 일을 막는다.

폴더가 없거나 비어 있으면 표식 파일을 만들고 쓴다. 표식 파일이 있는 폴더(이 도구가 만든 폴더)는
안의 내용을 모두 지우고 다시 쓴다. 표식 없이 무언가 들어 있는 폴더는 건드리지 않고 거부한다.
"""
from __future__ import annotations

import shutil
from pathlib import Path

MARKER = ".ucg-assist-output"


class OutputDirError(Exception):
    pass


def prepare(out: Path) -> None:
    if out.exists():
        if not out.is_dir():
            raise OutputDirError(f"출력 경로가 폴더가 아닙니다: {out}")
        entries = list(out.iterdir())
        if entries and not (out / MARKER).is_file():
            raise OutputDirError(f"이 도구가 만든 폴더가 아니어서 비우지 않습니다: {out}")
        for e in entries:
            if e.is_dir() and not e.is_symlink():
                shutil.rmtree(e)
            else:
                e.unlink()
    out.mkdir(parents=True, exist_ok=True)
    (out / MARKER).write_text("이 폴더는 다음 실행 때 비워집니다.\n", encoding="utf-8")
