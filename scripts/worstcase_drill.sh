#!/usr/bin/env bash
# Prove that the content repository alone can produce a safe static site.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source_repo="${1:-"${repo_root}/content"}"
python_bin="${UNSTACKED_PYTHON:-python3}"

if ! command -v "${python_bin}" >/dev/null; then
  echo "Python interpreter not found: ${python_bin}" >&2
  exit 2
fi
if ! "${python_bin}" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))'; then
  echo "worst-case drill requires Python 3.10 or newer (set UNSTACKED_PYTHON)" >&2
  exit 2
fi

if [[ ! -f "${source_repo}/mkdocs.yml" || ! -f "${source_repo}/requirements.txt" || ! -d "${source_repo}/docs" ]]; then
  echo "content repository must contain mkdocs.yml, requirements.txt, and docs/: ${source_repo}" >&2
  exit 2
fi

work_dir="$(mktemp -d "${TMPDIR:-/tmp}/unstacked-worstcase.XXXXXX")"
trap 'rm -rf "${work_dir}"' EXIT
copy_repo="${work_dir}/content"
venv_dir="${work_dir}/venv"
draft_slug="worstcase-draft-sentinel"
draft_title="Worst-case Draft Sentinel"

# Use only the standard library to copy the portable repository.  In
# particular, neither this script nor the copied tree imports the app or reads
# its database.  Existing site output is deliberately excluded.
SOURCE_REPO="${source_repo}" COPY_REPO="${copy_repo}" "${python_bin}" - <<'PY'
import os
import shutil

shutil.copytree(
    os.environ["SOURCE_REPO"],
    os.environ["COPY_REPO"],
    ignore=shutil.ignore_patterns("site", ".venv", "__pycache__"),
)
PY

cat > "${copy_repo}/docs/${draft_slug}.md" <<EOF
---
title: ${draft_title}
draft: true
---

# ${draft_title}
EOF

"${python_bin}" -m venv "${venv_dir}"
"${venv_dir}/bin/python" -m pip install --disable-pip-version-check -r "${copy_repo}/requirements.txt"
"${venv_dir}/bin/python" -m mkdocs build --strict --config-file "${copy_repo}/mkdocs.yml"

if [[ -e "${copy_repo}/site/${draft_slug}/index.html" ]]; then
  echo "draft page was emitted as HTML" >&2
  exit 1
fi
if grep -Fq "${draft_title}" "${copy_repo}/site/search/search_index.json"; then
  echo "draft page was emitted in the static search index" >&2
  exit 1
fi

echo "Worst-case recovery drill passed: portable content built without drafts."
