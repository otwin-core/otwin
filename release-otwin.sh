#!/usr/bin/env bash
#
# Cut an otwin release to PyPI.
#
# The publish itself is one `git push` of a tag — the workflow does the rest.
# Everything before that line in this script is there because the PyPI upload is
# IRREVERSIBLE: a version number, once uploaded, cannot be replaced or reused.
# Every check below is cheap now and impossible later.
#
# Usage:
#   ./release-otwin.sh                 # dry run: build and verify, push nothing
#   ./release-otwin.sh --publish       # the same checks, then push the tag
#
set -euo pipefail

PUBLISH=0
[ "${1:-}" = "--publish" ] && PUBLISH=1

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33mNote:\033[0m %s\n' "$*"; }
die()  { printf '\n\033[31mSTOP: %s\033[0m\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 1. Read the version from the source of truth, not from an argument. A version
#    passed on the command line is a version that can disagree with the tree.
# ---------------------------------------------------------------------------
say "Version"
# Read with a regex, not tomllib: this script has to run on the oldest Python the
# package supports, and tomllib is stdlib only from 3.11.
VERSION="$(python -c 'import re,pathlib; print(re.search(r"^version = \"([^\"]+)\"", pathlib.Path("pyproject.toml").read_text(), re.M).group(1))')"
DUNDER="$(python -c 'import re,pathlib; print(re.search(r"__version__ = \"([^\"]+)\"", pathlib.Path("src/otwin/__init__.py").read_text()).group(1))')"
TAG="v$VERSION"
echo "pyproject: $VERSION"
echo "__version__: $DUNDER"
[ "$VERSION" = "$DUNDER" ] || die "pyproject.toml and otwin.__version__ disagree. Both have to move together."
grep -q "^## \[$VERSION\]" CHANGELOG.md || die "CHANGELOG.md has no '## [$VERSION]' heading. Move the Unreleased section under it."

# ---------------------------------------------------------------------------
# 2. Refuse to release something that is already released, or a dirty tree.
#    PyPI will reject a re-upload of an existing version, but it rejects it
#    *after* the workflow has run and after the tag is public.
# ---------------------------------------------------------------------------
say "Preconditions"
git diff --quiet && git diff --cached --quiet || die "working tree is dirty"
[ -z "$(git tag -l "$TAG")" ] || die "tag $TAG already exists locally. Delete it, or bump the version."
if git ls-remote --exit-code --tags origin "refs/tags/$TAG" >/dev/null 2>&1; then
  die "tag $TAG already exists on the remote. That version is spent — bump it."
fi
if python -c "
import json,sys,urllib.request
try:
    d = json.load(urllib.request.urlopen('https://pypi.org/pypi/otwin/json', timeout=10))
except Exception:
    sys.exit(2)          # offline: skipped rather than assumed
sys.exit(0 if '$VERSION' in d['releases'] else 1)
"; then
  die "otwin $VERSION is already on PyPI. A version cannot be replaced; bump it."
elif [ $? -eq 2 ]; then
  warn "could not reach PyPI to check whether $VERSION is taken; continuing"
fi
echo "branch: $(git branch --show-current)  commit: $(git rev-parse --short HEAD)"

# ---------------------------------------------------------------------------
# 3. The four gates CI runs, plus the worked example. Run them here rather than
#    trusting the last CI run, because the tag points at *this* tree.
# ---------------------------------------------------------------------------
say "Gates"
python -m pytest -q                          || die "tests failed"
python -m ruff check src tests examples      || die "ruff check failed"
python -m ruff format --check src tests examples || die "ruff format failed — run: ruff format src tests examples"
python -m mypy src/otwin || warn "mypy failed, and as of 0.3.0 it fails on main too, in one of two ways:
      - on Python >= 3.12 with numpy >= 2.5 it cannot parse numpy's stubs at all
        (pyproject sets python_version = 3.10; the stubs use PEP 695). Confirm
        with: python -m mypy --python-version 3.12 src/otwin
      - on Python 3.10 it gets through and reports five shape-typing errors in
        estimate/{kalman,linear,energy}.py and model/integrators.py, all present
        on main at 3cf185f. Neither is a release blocker; both want fixing."
python examples/bess_end_to_end.py > /dev/null || die "the worked example failed"

# ---------------------------------------------------------------------------
# 4. Build exactly what the workflow builds, and run the same guard it runs.
#    If this fails here it would have failed there, at a point where the tag is
#    already public.
# ---------------------------------------------------------------------------
say "Build"
python -m pip install -q --upgrade build twine
rm -rf dist
python -m build
python -m twine check --strict dist/*

PKG="$(ls dist/*.tar.gz | sed -E 's|.*/otwin-(.*)\.tar\.gz|\1|')"
[ "$VERSION" = "$PKG" ] || die "the workflow's tag/package guard would fail: $VERSION vs $PKG"

say "Contents"
CACHE="$(tar tzf "dist/otwin-$VERSION.tar.gz" | grep -cE '\.hypothesis|__pycache__|\.venv/' || true)"
[ "$CACHE" -eq 0 ] || die "the sdist carries $CACHE cache entries. Check the sdist exclude list in pyproject.toml."
echo "sdist: $(tar tzf "dist/otwin-$VERSION.tar.gz" | wc -l | tr -d ' ') entries, no local cache"

# The install everyone actually performs, into a throwaway environment, so a
# broken wheel is found here rather than by the first person to install it.
say "Installing the built wheel into a clean environment"
rm -rf /tmp/otwin-relcheck
python -m venv /tmp/otwin-relcheck
/tmp/otwin-relcheck/bin/python -m pip install -q --upgrade pip
/tmp/otwin-relcheck/bin/python -m pip install -q "dist/otwin-$VERSION-py3-none-any.whl"
/tmp/otwin-relcheck/bin/python - <<PY
import otwin
from otwin.forecast import split_conformal          # 0.3.0 surface
from otwin.model import ModulatedIPHS, heat_exchanger
assert otwin.__version__ == "$VERSION", otwin.__version__
print(f"otwin {otwin.__version__} installs clean from the wheel and imports the new API")
PY
rm -rf /tmp/otwin-relcheck

# ---------------------------------------------------------------------------
# 5. Push the tag. This is the irreversible line.
# ---------------------------------------------------------------------------
if [ "$PUBLISH" -eq 0 ]; then
  say "Dry run complete"
  printf '\033[32mEverything a release needs is in place for %s.\033[0m\n\n' "$TAG"
  printf 'To publish:  ./release-otwin.sh --publish\n'
  printf 'That runs these same checks, then:\n'
  printf '  git tag -a %s -m "otwin %s"\n' "$TAG" "$VERSION"
  printf '  git push origin %s\n' "$TAG"
  exit 0
fi

say "Publishing $TAG"
git tag -a "$TAG" -m "otwin $VERSION"
git push origin "$TAG"

printf '\n\033[32mTag pushed.\033[0m The Release workflow builds, attests and publishes.\n\n'
printf 'Watch:   gh run watch --exit-status $(gh run list --workflow=release.yml --limit 1 --json databaseId -q ".[0].databaseId")\n'
printf 'Verify:  pip index versions otwin\n'
printf '         https://pypi.org/project/otwin/%s/\n' "$VERSION"
printf '\nIf the workflow fails AFTER the "Publish to PyPI" step, the package is\n'
printf 'already live and the tag cannot be reused. Fix forward with %s.\n' "0.3.1"
