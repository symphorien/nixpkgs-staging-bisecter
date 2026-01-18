#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2024 Guillaume Girol <symphorien_bug@xlumurb.eu>
#
# SPDX-License-Identifier: MIT

import subprocess
import re
import hashlib
from pathlib import Path
from ast import literal_eval
from typing import Literal
from contextlib import contextmanager
from tempfile import TemporaryDirectory
from functools import reduce, cache
import os
import argparse


def run(cmd: list[str], verbose: bool=True, text: Literal[False]=False, **kwargs) -> subprocess.CompletedProcess[bytes]:
    """wrapper around subprocess.run that prints the command if verbose=True and fails if command fails"""
    if verbose:
        print("Running", " ".join(cmd))
    return subprocess.run(cmd, check=True, text=text, **kwargs)


def get_outputs(drv: str) -> list[str]:
    """gets the output paths of a drv file"""
    with open(drv) as f:
        txt = f.read()
    start = txt.index("[")
    txt = txt[start:]
    end = txt.index("]")
    txt = txt[: end + 1]
    data = literal_eval(txt)
    return [i[1] for i in data]


def is_built(drv: str) -> bool:
    """determines wether a drv file has been build locally

    actually whether its build outputs are present in the store
    """
    for line in get_outputs(drv):
        assert line.startswith("/nix/store")
        if Path(line).exists():
            return True
    return False


@cache
def get_git_folder() -> Path:
    path = run(["git", "rev-parse", "--git-dir"], verbose=False, stdout=subprocess.PIPE).stdout.decode("utf8", errors="ignore")
    return Path(path.strip()).resolve()

def get_good_refs() -> list[str]:
    """returns all references in the form refs/bisect/good-*"""
    repo = get_git_folder()
    return [str(i.relative_to(repo)) for i in (repo / "refs" / "bisect").glob("good-*")]


def git_rev_parse(rev: str) -> str:
    """canonicalize a reference to a commit hash"""
    return (
        run(["git", "rev-parse", rev], verbose=False, stdout=subprocess.PIPE)
        .stdout.decode("utf8", errors="ignore")
        .strip()
    )


def get_bisect_commits(bad: str, goods: list[str]) -> list[str]:
    """returns all commits that git bisect may visit if refs/bisect/bad is `bad` and refs/bisect-good* are `goods`, as commit hashes"""
    bad = git_rev_parse(bad)
    assert len(goods) >= 1
    out = run(
        ["git", "log", "--pretty=oneline", bad, "--not"] + goods,
        verbose=False,
        stdout=subprocess.PIPE,
    ).stdout.decode("utf8", errors="ignore")
    res = []
    for line in out.splitlines():
        if not line:
            continue
        words = line.strip().split(" ")
        commit = words[0]
        if commit != bad:
            res.append(commit)
    return res


def hash(string: str) -> str:
    """hashes a string"""
    m = hashlib.sha256()
    m.update(string.encode("utf8"))
    return m.hexdigest()


def cache_file_for(hash: str) -> Path:
    """returns the path to a cache file depending on this hash only

    its parent dir is guaranteed to exist
    """
    cachedir = os.environ.get("XDG_CACHE_HOME", os.environ["HOME"] + "/.cache")
    d = Path(cachedir) / "bisecter"
    d.mkdir(exist_ok=True)
    f = d / hash
    return f


def cache_for(hash: str) -> str | None:
    """returns the value cached for this hash, if any"""
    f = cache_file_for(hash)
    if f.exists():
        with f.open() as t:
            return t.read()
    return None


def write_cache_for(hash: str, value: str):
    """stores a value in on-disk cache for this hash"""
    f = cache_file_for(hash)
    with f.open("w") as t:
        t.write(value)


drv_re = re.compile(r"/nix/store/[^/ ]*\.drv")


def get_drvs_inner(commit: str, cmd: list[str]) -> set[str]:
    """check-out this commit, and runs this command with --dry-run and parses all drvs that would be built"""
    run(["git", "checkout", commit])
    out = run(cmd + ["--dry-run"], stderr=subprocess.PIPE).stderr.decode(
        "utf8", errors="ignore"
    )
    return set(drv_re.findall(out))


def get_drvs(commit: str, cmd: list[str]) -> set[str]:
    """check-out this commit, and runs this command with --dry-run and parses all drvs that would be built

    memoized
    """
    h = hash(commit + ";" + ";".join(cmd))
    t = cache_for(h)
    if t is not None:
        v = literal_eval(t)
    else:
        v = get_drvs_inner(commit, cmd)
        write_cache_for(h, repr(v))
    return {drv for drv in v if not is_built(drv)}


@contextmanager
def worktree():
    """context manager that sets up a temporary git worktree at HEAD"""
    pwd = os.getcwd()
    exc = None
    with TemporaryDirectory() as tmpdir:
        f = str(tmpdir) + "/w"
        run(["git", "worktree", "add", f, "HEAD"])
        os.chdir(f)
        try:
            yield
        except BaseException as e:
            exc = e
    os.chdir(pwd)
    run(["git", "worktree", "prune"])
    if exc:
        raise exc


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="""computes good commits to build next in mass-rebuild-heavy git bisect (best first).

        Contrary to git bisect, this programs attempts to minimize the number
        of rebuilds the specified command needs instead of the number of
        visited commits. It runs the command with --dry-run on every commits in
        the git bisect range so it is notably slower than other helpers like
        hydrasect. Actually you should probably only use this program when
        hydrasect returns no good revision.

        The command is assumed to only read files checked out in git for
        aggressive caching; if it reads other files and that you change these
        files between runs of this program, nuke $XDG_CACHE_HOME/bisecter.

        """
    )
    parser.add_argument(
        "cmd",
        nargs=argparse.REMAINDER,
        help="""Command that builds the desired derivation. must accept an
        additional --dry-run flag, and output the drv files that would be built
        on stderr. In practice this must be nix-build or a wrapper of it.""",
    )
    parser.add_argument(
        "--checkout",
        help="checkout best candidate after computation",
        action="store_true",
    )
    args = parser.parse_args()
    if len(args.cmd) == 0:
        print("no command given")
        exit(1)
    goods = get_good_refs()
    bad = "refs/bisect/bad"
    commits = get_bisect_commits(bad=bad, goods=goods)
    n = len(commits)
    print("found", n, "commits")
    rebuilds = {}
    with worktree():
        for commit in commits:
            rebuilds[commit] = get_drvs(commit, args.cmd)
    weights = []
    for commit in commits:
        candidates_if_good = get_bisect_commits(bad=bad, goods=goods + [commit])
        candidates_if_bad = get_bisect_commits(bad=commit, goods=goods)
        rebuilds_if_good = len(
            reduce(lambda a, b: a | b, (rebuilds[i] for i in candidates_if_good), set())
            - rebuilds[commit]
        )
        rebuilds_if_bad = len(
            reduce(lambda a, b: a | b, (rebuilds[i] for i in candidates_if_bad), set())
            - rebuilds[commit]
        )
        w = (
            len(rebuilds[commit])
            + (
                len(candidates_if_good) * rebuilds_if_good
                + len(candidates_if_bad) * rebuilds_if_bad
            )
            / n
        )
        weights.append(
            (
                w,
                commit,
                len(candidates_if_good),
                len(candidates_if_bad),
                rebuilds_if_good,
                rebuilds_if_bad,
            )
        )
    weights.sort()
    print(
        "commit                                          ",
        "estimated cost",
        "rebuilds",
        "commits>",
        "rebuilds>",
        "commits<",
        "rebuilds<",
        sep="\t",
    )
    for (
        score,
        commit,
        candidates_if_good,
        candidates_if_bad,
        rebuilds_if_good,
        rebuilds_if_bad,
    ) in weights[:5]:
        print(
            commit,
            int(score),
            len(rebuilds[commit]),
            candidates_if_good,
            rebuilds_if_good,
            candidates_if_bad,
            rebuilds_if_bad,
            sep="\t\t",
        )
    if args.checkout:
        run(["git", "checkout", weights[0][1]])
