#!/usr/bin/env bash
#
# Release-tag authorization.
#
# A release publishes bytes under this repository's name. This script decides
# whether the tag naming those bytes is one the maintainer actually signed,
# and it runs before any job that builds or uploads anything.
#
# What it enforces, in order:
#
#   1. A tag was actually resolved. A dispatch from a branch resolves nothing,
#      and "publish whatever the dispatch happens to point at" is the hole this
#      exists to close, so an unresolved tag is a failure and not a skip.
#   2. The grandfather list contains only literal vX.Y.Z tag names. An
#      allow-list that can be widened to a glob is a gate that stops covering
#      what it names without anything going red, so widening it fails here.
#   3. The tag is an annotated tag object, not a lightweight ref.
#   4. Its SSH signature verifies against the repository's own committed
#      allowed-signers file. The file is read at the verified ref, so trusting
#      it is the same trust decision as running this script at all.
#   5. The commit the tag selects is the commit being built (EXPECT_COMMIT).
#      Without this the signature check is theatre: it would prove some tag was
#      signed while the build ran from something else.
#
# Grandfathering. Tags cut before this control existed cannot be re-signed --
# rewriting a published tag is worse than the gap it would close. Each caller
# passes GRANDFATHERED_TAGS naming exactly those tags, and the workflow that
# calls this says which ones and why. Every tag not on that list is verified,
# including tags that already exist and already pass.
#
# Inputs, all through the environment rather than argv, because the tag name
# reaches this script from `github` context data:
#
#   RELEASE_TAG         github.event.release.tag_name ("" outside a release)
#   REF_TYPE/REF_NAME   github.ref_type / github.ref_name
#   EXPECT_COMMIT       github.sha, the commit this run is building ("" to skip)
#   ALLOWED_SIGNERS     path to the committed allowed-signers file
#   GRANDFATHERED_TAGS  space-separated literal tag names that predate this

set -euo pipefail

ALLOWED_SIGNERS="${ALLOWED_SIGNERS:-.github/allowed_signers}"
GRANDFATHERED_TAGS="${GRANDFATHERED_TAGS:-}"
RELEASE_TAG="${RELEASE_TAG:-}"
REF_TYPE="${REF_TYPE:-}"
REF_NAME="${REF_NAME:-}"
EXPECT_COMMIT="${EXPECT_COMMIT:-}"

fail() { printf '::error::%s\n' "$*" >&2; exit 1; }
note() { printf '::notice::%s\n' "$*"; }

# 1. Which tag is being released.
TAG="${RELEASE_TAG}"
if [ -z "${TAG}" ] && [ "${REF_TYPE}" = "tag" ]; then
  TAG="${REF_NAME}"
fi
if [ -z "${TAG}" ]; then
  fail "No release tag could be resolved from this event. Publish from a GitHub Release, or dispatch this workflow from a vX.Y.Z tag ref; a dispatch from a branch has no tag to verify and must not publish."
fi

# 2. The grandfather list may only name literal tags.
for entry in ${GRANDFATHERED_TAGS}; do
  if [[ ! "${entry}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    fail "GRANDFATHERED_TAGS entry '${entry}' is not a literal vX.Y.Z tag name. This list exempts named history; a pattern here would exempt the future too."
  fi
done

# The tag object itself, fetched from origin so a stale local ref cannot decide this.
if git remote get-url origin >/dev/null 2>&1; then
  git fetch --force --quiet origin "refs/tags/${TAG}:refs/tags/${TAG}"
fi
if ! git rev-parse -q --verify "refs/tags/${TAG}" >/dev/null; then
  fail "Tag ${TAG} does not exist in this repository."
fi
COMMIT="$(git rev-parse --verify "refs/tags/${TAG}^{commit}")"

# 5. The tag has to select the commit this run is building, whatever else is true.
if [ -n "${EXPECT_COMMIT}" ] && [ "${COMMIT}" != "${EXPECT_COMMIT}" ]; then
  fail "Tag ${TAG} points at ${COMMIT}, but this run is building ${EXPECT_COMMIT}. Refusing to publish a build that the verified tag does not name."
fi

if [ -n "${GITHUB_OUTPUT:-}" ]; then
  {
    printf 'tag=%s\n' "${TAG}"
    printf 'commit=%s\n' "${COMMIT}"
  } >> "${GITHUB_OUTPUT}"
fi

for entry in ${GRANDFATHERED_TAGS}; do
  if [ "${entry}" = "${TAG}" ]; then
    note "${TAG} predates release-tag signing in this repository and is named in GRANDFATHERED_TAGS. Its signature is not checked; every other tag's is. See the calling workflow for why this one is on the list."
    exit 0
  fi
done

# 3. Annotated tag object, not a lightweight ref.
TAG_TYPE="$(git cat-file -t "refs/tags/${TAG}")"
if [ "${TAG_TYPE}" != "tag" ]; then
  fail "${TAG} is a ${TAG_TYPE}, not an annotated tag object, so it carries no signature. Cut release tags with: git tag -s ${TAG} -m \"release: ${TAG}\""
fi

# 4. Signed by a principal this repository has committed to trusting.
if [ ! -s "${ALLOWED_SIGNERS}" ]; then
  fail "${ALLOWED_SIGNERS} is missing or empty, so no signature could be trusted against it."
fi
if ! grep -q '^[^#[:space:]].*ssh-' "${ALLOWED_SIGNERS}"; then
  fail "${ALLOWED_SIGNERS} contains no ssh public key line."
fi

if ! git -c gpg.format=ssh \
        -c "gpg.ssh.allowedSignersFile=${PWD}/${ALLOWED_SIGNERS}" \
        verify-tag -- "${TAG}" >/tmp/verify-release-tag.log 2>&1; then
  printf '::error::%s\n' "${TAG} is not signed by a key listed in ${ALLOWED_SIGNERS}. Nothing is published from an unverifiable tag." >&2
  cat /tmp/verify-release-tag.log >&2
  exit 1
fi
cat /tmp/verify-release-tag.log
note "${TAG} verified against ${ALLOWED_SIGNERS}; it selects ${COMMIT}."
