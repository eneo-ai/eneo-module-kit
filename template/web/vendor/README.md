# vendor/

As the template ships, it installs `@eneo-ai/module-kit` as a checkout of the kit builds it (the kit's CI builds the template
against the packages of the same commit), so the lock cannot name an address for it. The lock (`package-lock.json`) instead says the package is version `0.1.0` and found here, in
`vendor/eneo-ai-module-kit-<version>.tgz`, with no hash (it is the kit's own build, which changes with every commit of the UI
package). Every other package is locked with its hash.

- **Install** (`npm ci`): put the packed UI package here first. From the kit repository: `npm run -w packages/ui build &&
  npm pack -w packages/ui --pack-destination <this folder>`. The kit's `Dockerfile` does it from the `kit` build context.
- **Change a dependency or the kit's version**: `node scripts/relock.mjs /path/to/the-tarball.tgz`, which regenerates the lock.
- **From the kit's GitHub release** instead: delete this folder and `scripts/relock.mjs`, and install the release's tarball by
  its address ([where the packages come from](https://github.com/eneo-ai/eneo-module-kit/blob/main/docs/guides/new-module.md#where-the-packages-come-from)): the lock then names that address, with its
  hash, and `npm ci` needs nothing here. The package is not on npm yet; once it is, a version from the registry works the same.

The tarball itself is not committed (`.gitignore`).
