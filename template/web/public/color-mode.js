// The stored colour mode before the first paint. index.html runs this file of the page's own origin, in the head, before
// the page is drawn: the policy allows no inline script. It does what the design system's <Theme mode> does once React
// runs: `data-theme` on <html> for a chosen light or dark, none for system (the browser's preference decides). The key and
// values are @eneo-ai/module-kit's (COLOR_MODE_KEY, "theme"); storage that is missing or throws is no choice.
(function () {
  try {
    var mode = localStorage.getItem("theme");
    if (mode === "light" || mode === "dark") document.documentElement.setAttribute("data-theme", mode);
  } catch (e) {}
})();
