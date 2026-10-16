# K18. A release gives the tested image its version; the deployment names the release

Purpose: say why a module's release copies the image CI tested instead of building one, and why the release a module shows comes from its deployment.
Read this when: you change the template's workflows, its Dockerfile's build arguments, its compose file, `/health`, or how a module shows its version.
Related: [deploy](../guides/deploy.md), [configuration](../guides/configuration.md#which-build-runs), [new module](../guides/new-module.md#ci), [K1](k01-one-repository-three-parts.md).

Status: Implemented, 2026-10-16. Adopted from speech-to-text's release path. Source: `template/.github/workflows/ci.yml`, `release.yml`, `template/Dockerfile`, `template/docker-compose.yml`, `packages/bff/src/eneo_module_bff/build.py`.

## Context

A module is one image. If a release built its image again, what runs in production would be bytes nobody tested: a new base image, a moved dependency or a flaky build could change between the commit's CI and the tag. And a version written into the image at build time cannot exist for an image that is built before anyone decides to release it.

## Decision

CI builds the image once per commit, with its SBOM and provenance, runs it as the compose file runs it, and on main pushes those bytes as `sha-<commit>` only after every job passed. A tag `vX.Y.Z` on a commit of main copies that digest, registry to registry, to `vX.Y.Z` and `latest`, after checking that the image's `org.opencontainers.image.revision` label is the tagged commit. The release builds nothing.

The image says what it was built from: the commit, the build time and the repository, from build arguments, in its OCI labels and in the environment the BFF reads. The release is the deployment's: `MODULE_VERSION` chooses the image's tag in the compose file, which passes the same value into the container. `/health` answers all four, each `null` when not known; only a version tag counts as a release. The UI has no version of its own: it shows what `/health` answers.

## Consequences

A commit that CI has not passed on main has no image and cannot be released; a tag pushed while CI still runs waits for it. A deployment of `latest` shows no release, only its commit. A local build says nothing of itself. The image's name is derived from the repository in the workflows and written once in the compose file, which CI checks. Actions are pinned to commits and images to digests, so the bytes a release ships are the ones CI saw, built from inputs that do not move by themselves.
