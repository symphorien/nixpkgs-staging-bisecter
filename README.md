<!--
SPDX-FileCopyrightText: 2024 Guillaume Girol <symphorien_bug@xlumurb.eu>

SPDX-License-Identifier: MIT
-->

# nixpkgs-staging-bisecter

`git bisect` is designed to find the commit introducing a regression within a
range by visiting the least commits. This is very handy to bisect regressions
in nixpkgs as long as everything is in the cache. However, `git bisect` sometimes
picks a commit introducing a mass rebuild.

One strategy is to override git's pick by choosing a nearby commit built by
hydra, ~see [hydrasect](https://git.qyliss.net/hydrasect/about/) for example~ (apparently [broken](https://github.com/NixOS/nixpkgs/issues/323985#issuecomment-2210893775)).
But at some point, you may end up bisecting inside a large range of commits
that where not built by hydra, for example staging. `nixpkgs-staging-bisecter`
is designed to spend some time choosing a better commit than `git bisect` by
attempting to minimize how many derivations you will build instead of the number
of visited commits.

This is only interesting when you expected to spend much more time building than
testing.

## Example
I am looking for a regression only visible in a vm built by 
```
nixos-rebuild build-vm -I nixos-config=temp/vm.nix -I nixpkgs=. --fast -j2
```

`nixpkgs-staging-bisecter` only supports commands starting by `nix-build` so here is the `nix-build` equivalent:
```
nix-build '<nixpkgs/nixos>' -A vm -I nixos-config=temp/vm.nix -I nixpkgs=. -j2
```

Additionally files not checked in nixpkgs must be referred as absolute path (the command will be run in other directories by `bisecter.py`):
```
nix-build '<nixpkgs/nixos>' -A vm -I nixos-config=/home/symphorien/src/nixpkgs/temp/vm.nix -I nixpkgs=. -j2
```

Then every time you run `git bisect good` or `git bisect bad`, run
```
bisecter.py --checkout nix-build '<nixpkgs/nixos>' -A vm -I nixos-config=/home/symphorien/src/nixpkgs/temp/vm.nix -I nixpkgs=. -j2
```

It will pick a commit that ensures that if you build 
`nixos-rebuild build-vm -I nixos-config=temp/vm.nix -I nixpkgs=. --fast -j2`,
the expected number of rebuilds left for the remainder of the bisection is
minimal, assuming the bug is uniformly distributed among possible commits.
(Actually the number of remaining builds is approximated, and that's only a rough estimation for build time, but it still seems useful).

The first run will run the specified nix-build command with `--dry-build` on all commits in the
git bisect range to determine rebuild counts, so this will be very slow, but
later calls use a cache and should not take more than a minute.

If you change the behavior of the command during the bisection (in my example by changing `temp/vm.nix`) you must invalidate the cache by nuking `$XDG_CACHE_HOME/bisecter`.

## Installing

`./bisecter.py` is just a python script with no dependencies.

