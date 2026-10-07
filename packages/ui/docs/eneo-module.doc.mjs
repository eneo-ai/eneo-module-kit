export default {
  type: 'generic',
  name: 'eneo-module',
  title: 'Build an Eneo module',
  description: 'Use the Eneo shell, session client and guarded backend with Astryx.',
  sections: [
    {
      title: 'Page workflow',
      content: [
        { type: 'prose', text: 'Run npm run astryx -- build "en sida i en Eneo-modul", then read template eneo-module-page or eneo-signin and component documentation for every Astryx component you use. Templates are reference source; adapt their names and data at the route that owns them.' },
        { type: 'prose', text: 'Use ModuleProviders once at the entry point. Import the kit layers.css, Astryx reset.css and astryx.css, and the kit theme.css and base.css. ModuleShell owns the top navigation, skip link and single main region. Cap page content with Layout and LayoutContent; do not add a second main.' },
      ],
    },
    {
      title: 'Session and backend',
      content: [
        { type: 'prose', text: 'Place private routes inside RequireSession and send requests with fetchWithSession from @eneo-ai/module-kit/session. Module-owned native dialogs must close while useSignedOut() is true; keep their draft state outside the dialog. The shared sign-in screen handles SSO and callback errors.' },
        { type: 'prose', text: 'A module owns its routes and allowlist. Declare require_session on every private route and require_same_origin on writes and WebSockets. Do not put module-specific routes or protocols into the kit. The backend, setup and configuration guides live in the kit repository, not in a copied module: https://github.com/eneo-ai/eneo-module-kit/blob/main/docs/README.md' },
      ],
    },
    {
      title: 'Design and verification',
      content: [
        { type: 'prose', text: 'Use the exact pinned Astryx version, components and Eneo theme. Fix shared component styling in the theme; use tokens for bespoke surfaces. No Next.js, Tailwind, authored StyleX or ejected components. User-facing text is Swedish and resources stay on the module origin.' },
        { type: 'prose', text: 'Keep loading, empty, error, retry and signed-out states usable. Add page states to web/tests/e2e/screens.ts, then run npm run build and npm run test:e2e in web/. The gate checks WCAG 2.2 AA, 44 px coarse-pointer targets, visible focus and responsive layouts in both colour modes.' },
      ],
    },
  ],
};
