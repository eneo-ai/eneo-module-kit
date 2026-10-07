export default {
  templates: './templates',
  docs: './docs',

  agentDocs: {
    append: [
      'Run Astryx through npm run astryx --; keep its core and CLI at the exact pinned version.',
      'Read astryx docs eneo-module; start a page from eneo-module-page or eneo-signin and inspect every component prop.',
      'Use ModuleProviders once; ModuleShell owns navigation, the skip link and the one main region. Cap content with Layout.',
      'Private routes use RequireSession and fetchWithSession; close module-owned native dialogs while useSignedOut() is true.',
      'Backend routes require require_session; writes and WebSockets also require require_same_origin. The module owns its allowlist.',
      'Use Astryx components and Eneo theme tokens; no Next.js, Tailwind, authored StyleX or ejected components.',
      'User-facing text is Swedish; fonts and scripts stay on the module origin. Keep 44 px touch targets and visible focus.',
      'Add every page state to web/tests/e2e/screens.ts and run web build and test:e2e before finishing.'
    ]
  }
};
