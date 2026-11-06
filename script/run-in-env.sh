#!/usr/bin/env sh
set -eu

# The venv's activate script reads OSTYPE, which set -u makes an error while it is unset.
OSTYPE="${OSTYPE-}"

# Use the main checkout's virtual environment, so the command also runs in a worktree.
root=$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")
. "$root/.venv/bin/activate"

exec "$@"
