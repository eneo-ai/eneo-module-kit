# vendor/

Before the kit's first release `@eneo-ai/module-kit` is not in the npm registry, so the lock cannot name a registry address for
it. The lock (`package-lock.json`) instead says the package is version `0.1.0` and found here, in
`vendor/eneo-ai-module-kit-<version>.tgz`, with no hash (it is the kit's own build, which changes with every commit of the UI
package). Every other package is locked with its hash.

- **Install** (`npm ci`): put the packed UI package here first. From the kit repository: `npm run -w packages/ui build &&
  npm pack -w packages/ui --pack-destination <this folder>`. The kit's `Dockerfile` does it from the `kit` build context.
- **Change a dependency or the kit's version**: `node scripts/relock.mjs /path/to/the-tarball.tgz`, which regenerates the lock.
- **After the release**: delete this folder and `scripts/relock.mjs`, and run `npm install @eneo-ai/module-kit@<version>`: the
  lock then names the registry, with its hash, and `npm ci` needs nothing here.

The tarball itself is not committed (`.gitignore`).
