// How the compiled unit tests find a source (tests/unit/setup.mjs registers this): `./config`, as the bundler resolves
// it, is `./config.js` once compiled.
export async function resolve(specifier, context, nextResolve) {
  try {
    return await nextResolve(specifier, context);
  } catch (error) {
    if (error?.code !== "ERR_MODULE_NOT_FOUND" || !/^\.\.?\//.test(specifier)) throw error;
    return nextResolve(`${specifier}.js`, context);
  }
}
