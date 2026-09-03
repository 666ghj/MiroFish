/**
 * JavaScript mirror of the design tokens that d3 and other canvas renderers
 * need. Canvas and SVG attributes set from script cannot read a CSS custom
 * property, so the graph palette is duplicated here.
 *
 * These values MUST stay identical to the --graph-* block in tokens.css.
 * Change one, change the other.
 */

/** Categorical series colours, in assignment order. All >= 6:1 on --bg-canvas. */
export const graphPalette = [
  '#FF8B00',
  '#38BDF8',
  '#A78BFA',
  '#34D399',
  '#FF8FA3',
  '#FBBF24',
  '#22D3EE',
  '#F472B6',
  '#93C5FD',
  '#FDBA74'
]

/** Structural colours for nodes, edges and labels in the knowledge graph. */
export const graphColors = {
  edge: '#4A67AB',
  edgeHighlight: '#38BDF8',
  nodeStroke: '#071952',
  label: '#C9D6F2'
}

/**
 * Surface, text and status colours needed by script-driven renderers.
 *
 * Ratios in the trailing comments are canvas / panel / raised / overlay,
 * matching the four-surface table at the top of tokens.css.
 */
export const themeColors = {
  bgCanvas: '#071952',
  bgSunken: '#04102F',
  bgPanel: '#0D2668',
  bgRaised: '#12307D',
  bgOverlay: '#163A8E',
  borderDefault: '#1E3D8F',
  borderStrong: '#2A4E99',
  textPrimary: '#FFFFFF', //   16.54 / 14.05 / 12.04 / 10.35
  textSecondary: '#C9D6F2', // 11.33 /  9.63 /  8.24 /  7.09
  textMuted: '#AFBEE5', //      8.91 /  7.58 /  6.49 /  5.58
  textFaint: '#99AFE8', //      7.60 /  6.46 /  5.53 /  4.75
  textOnAccent: '#071952', //   7.04 on --accent
  accent: '#FF8B00',
  accentHover: '#FFA333',
  success: '#34D399',
  warning: '#FBBF24',
  danger: '#FF8FA3',
  info: '#38BDF8',
  neutralDot: '#9AAEDB' //      7.44 /  6.33 /  5.42 /  4.66
}

/** Font stacks, for renderers that set a font string rather than a CSS class. */
export const fontStacks = {
  sans: "'Space Grotesk', 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
  mono: "'JetBrains Mono', ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace"
}

/**
 * Pick a categorical colour for an index, wrapping past the end of the palette.
 *
 * PART OF THE PUBLIC TOKEN API. Nothing in the app imports it today -
 * GraphPanel.vue destructures `graphPalette` into named constants instead - so
 * it is deliberately kept, not dead code left behind by accident. It is the
 * supported way for a future canvas or SVG renderer to index the palette
 * without re-implementing the wrap, including for negative indices.
 *
 * @param {number} index Zero-based series index; negative values wrap too.
 * @returns {string} A hex colour from graphPalette.
 */
export function graphColorAt (index) {
  return graphPalette[((index % graphPalette.length) + graphPalette.length) % graphPalette.length]
}
