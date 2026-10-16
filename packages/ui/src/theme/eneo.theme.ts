import {defineTheme} from '@astryxdesign/core/theme';

const focusRing = {
  outline: 'var(--focus-outline-width) var(--focus-outline-style) var(--focus-outline-color)',
  outlineOffset: 'var(--focus-outline-offset)',
};
// A menu's rows sit edge to edge in a clipping box: their ring is drawn inside them.
const rowFocusRing = {...focusRing, outlineOffset: 'calc(var(--focus-outline-width) * -1)'};
// A field's rounded edge owns its focus indicator; no second box or inner shadow.
const fieldFocusRing = {...focusRing, outlineOffset: 'calc(var(--border-width) * -1)', boxShadow: 'none'};
const TOUCH = '44px';

export const eneoTheme = defineTheme({
  name: 'eneo',
  color: {accent: ['#004595', '#52B1FF'], neutralStyle: 'neutral', contrast: 'standard'},
  typography: {
    scale: {base: 16, ratio: 1.2},
    body: {family: 'system-ui', fallbacks: '-apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif'},
    code: {family: 'ui-monospace', fallbacks: '"SFMono-Regular", Consolas, monospace'},
  },
  tokens: {
    '--color-accent': ['#004595', '#52B1FF'],
    '--color-on-accent': ['#FFFFFF', '#0B1118'],
    // Astryx's default white label on the dark-mode error fill is 3.76:1; a dark label is 5.4:1.
    '--color-on-error': ['#FFFFFF', '#1A0A0C'],
    // The one action a screen exists for (Starta, Stoppa, Skapa dokument) is 48 px at every pointer; Astryx's
    // large control is 36 px with a mouse.
    '--size-element-lg': '48px',
    // Supporting text is read at 14 px and still follows the reader's root font size.
    '--font-size-sm': '0.875rem',
    // Error text and control edges meet AA on the page, card and muted surface.
    '--color-error': ['#AA181D', '#F47B7F'],
    '--color-border-emphasized': ['#85868F', '#626972'],
  },
  components: {
    // A word with no break point (an e-mail address as a name, a long compound) wraps instead of reaching past a
    // 320 px screen: Astryx breaks words only when it truncates.
    // A heading that wraps balances its lines: "Dokumentet kunde inte skapas" does not leave "skapas" alone on a phone.
    // A phase's heading takes focus when its view appears (usePhaseHeading) but is no control: the browser counts that
    // focus call as keyboard focus and would frame the headline on every visit.
    heading: {base: {overflowWrap: 'anywhere', textWrap: 'balance', ':focus-visible': {outline: 'none'}}},
    text: {base: {overflowWrap: 'anywhere'}},
    'top-nav': {base: {columnGap: 'var(--spacing-2)'}},
    'top-nav-heading': {base: {minInlineSize: '0'}},
    'text-input': {base: {':focus-within': fieldFocusRing}},
    'text-area': {base: {':focus-within': fieldFocusRing}},
    'number-input': {base: {':focus-within': fieldFocusRing}},
    selector: {base: {':focus-within': fieldFocusRing}},
    typeahead: {base: {':focus-within': fieldFocusRing}},
    tokenizer: {base: {':focus-within': fieldFocusRing}},
    // The radio rows of a menu show no focus at all (a plain row tints, a radio row does not).
    'dropdown-menu-item': {base: {':focus-visible': rowFocusRing}},
    // A long compound word or e-mail address wraps inside its row instead of being cut off by it.
    item: {base: {overflowWrap: 'anywhere'}},
    // A table's header cells keep one line and cut the rest off with an ellipsis, where the cells under them wrap: a
    // heading such as "Belopp, tkr" loses its unit on a phone (WCAG 1.4.10).
    'table-header-cell': {base: {whiteSpace: 'normal', textOverflow: 'clip', overflowWrap: 'break-word', wordBreak: 'break-word'}},
    // Scroll shadows show that a narrow table has more columns, at the edge that has more, without another control or
    // wrapper: the card-coloured covers scroll with the content and uncover the shadows only where it continues.
    'table-scroll-wrapper': {base: {
      backgroundImage: 'linear-gradient(to right, var(--color-background-card), transparent), linear-gradient(to left, var(--color-background-card), transparent), radial-gradient(farthest-side at 0 50%, var(--color-border), transparent), radial-gradient(farthest-side at 100% 50%, var(--color-border), transparent)',
      backgroundPosition: 'left center, right center, left center, right center',
      backgroundSize: 'var(--spacing-6) 100%, var(--spacing-6) 100%, var(--spacing-2) 100%, var(--spacing-2) 100%',
      backgroundRepeat: 'no-repeat',
      backgroundAttachment: 'local, local, scroll, scroll',
    }},
    // The control is the slider's target (the track is 4 px, the thumb 20): the gate's 24 px, and 44 px below.
    'slider-control': {base: {minBlockSize: '24px'}},
    // A label longer than its line wraps and the button grows with it: the design system keeps one line, cuts the rest
    // off with an ellipsis and fixes the height (WCAG 1.4.10 reflow at 320 px, 1.4.4 resize at 200 %). The block padding
    // is small enough that a one-line label still fills the size's own height: 28, 32 and 36 px.
    button: {
      base: {whiteSpace: 'normal', height: 'auto', minHeight: 'var(--size-element-md)', paddingBlock: 'var(--spacing-0-5)'},
      'size:sm': {minHeight: 'var(--size-element-sm)'},
      'size:lg': {minHeight: 'var(--size-element-lg)'},
    },
    // The initials sit on a tint of the neutral colour; the secondary text colour on it, over the page's surface, is
    // 4.28:1 in dark mode, the primary one 8.5:1.
    'avatar-fallback': {base: {color: 'var(--color-text-primary)'}},
    // An off switch's track is a control's edge colour: 3:1 on the page and under its thumb, which is the surface's
    // colour (WCAG 1.4.11); the design system's translucent grey is 1.5:1. Set as the grey the switch's own off, hover and
    // disabled rules read, so its on track and its forced-colours tracks stay the design system's.
    switch: {base: {'--color-background-gray': 'var(--color-border-emphasized)'}},
  },
  adaptations: {
    rules: [
      {
        when: {pointer: 'coarse'},
        value: {
          tokens: {'--size-element-sm': TOUCH, '--size-element-md': TOUCH, '--size-element-lg': '48px'},
          components: {
            'dropdown-menu-item': {base: {minHeight: TOUCH}},
            'selector-option-row': {base: {minHeight: TOUCH}},
            'typeahead-item': {base: {minHeight: TOUCH}},
            'top-nav-heading': {base: {minHeight: TOUCH}},
            'slider-control': {base: {minBlockSize: TOUCH}},
            'collapsible-trigger': {base: {minHeight: TOUCH}},
            // A one-line text area can shrink to 32 px on a tablet; the field itself stays a touch target.
            'text-area-control': {base: {minBlockSize: TOUCH}},
          },
        },
      },
    ],
  },
});
