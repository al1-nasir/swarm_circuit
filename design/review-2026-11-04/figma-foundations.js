/**
 * createVariableCollection
 *
 * Creates a new Figma variable collection with the specified name and modes.
 * If `modeNames` has more than one entry, the first mode is renamed from
 * Figma's default "Mode 1" to the first name, and additional modes are added.
 *
 * @param {string} name - The display name of the collection (e.g. "Color", "Spacing").
 * @param {string[]} modeNames - Ordered list of mode names (e.g. ["Light", "Dark"] or ["Value"]).
 * @returns {Promise<{
 *   collection: VariableCollection,
 *   modeIds: Record<string, string>
 * }>}
 *   `modeIds` maps each mode name to its modeId string.
 */
async function createVariableCollection(name, modeNames) {
  if (!modeNames || modeNames.length === 0) {
    throw new Error('createVariableCollection: modeNames must have at least one entry.')
  }

  // Create the collection — Figma always creates it with one mode named "Mode 1".
  const collection = figma.variables.createVariableCollection(name)

  // modeIds accumulator
  const modeIds = {}

  // Rename the default first mode
  const defaultMode = collection.modes[0]
  collection.renameMode(defaultMode.modeId, modeNames[0])
  modeIds[modeNames[0]] = defaultMode.modeId

  // Add additional modes
  for (let i = 1; i < modeNames.length; i++) {
    const newModeId = collection.addMode(modeNames[i])
    modeIds[modeNames[i]] = newModeId
  }

  return { collection, modeIds }
}

/**
 * createSemanticTokens
 *
 * Creates a batch of Figma variables in the given collection, one per entry in
 * `tokenMap`. Supports raw values, variable alias references, code syntax, and
 * scopes. Returns a map of token name → Variable for use in subsequent steps.
 *
 * @param {VariableCollection} collection - The target variable collection.
 * @param {Record<string, string>} modeIds - Map of {modeName: modeId} from createVariableCollection.
 * @param {Array<{
 *   name: string,
 *   type: 'COLOR' | 'FLOAT' | 'STRING' | 'BOOLEAN' | 'TIMING' | 'EASING',
 *   values: Record<string, string | number | boolean | MotionEasing | {type: 'VARIABLE_ALIAS', id: string}>,
 *   scopes?: VariableScope[],
 *   codeSyntax?: {WEB?: string, ANDROID?: string, iOS?: string}
 * }>} tokenMap - Ordered list of token definitions.
 *   - `name`: Variable name using slash hierarchy (e.g. "color/bg/primary").
 *   - `type`: Figma variable type.
 *   - `values`: Map of {modeName: value}. Values can be raw (hex string for COLOR,
 *     number for FLOAT) or alias objects {type: 'VARIABLE_ALIAS', id: variableId}.
 *     For COLOR, raw values are accepted as hex strings ("#rrggbb" or "#rrggbbaa")
 *     and converted to {r, g, b, a} automatically.
 *   - `scopes`: Array of VariableScope strings. Omit to use [] (hidden/primitive).
 *   - `codeSyntax`: Platform code syntax strings. Omit to skip.
 * @returns {Promise<{variables: Record<string, Variable>}>}
 *   `variables` maps each token name to its created Variable object.
 */
async function createSemanticTokens(collection, modeIds, tokenMap) {
  const variables = {}

  for (const token of tokenMap) {
    // Create the variable
    const variable = figma.variables.createVariable(token.name, collection, token.type)

    // Set values for each mode
    for (const [modeName, rawValue] of Object.entries(token.values)) {
      const modeId = modeIds[modeName]
      if (!modeId) {
        throw new Error(
          `createSemanticTokens: mode "${modeName}" not found in modeIds for token "${token.name}". ` +
            `Available modes: ${Object.keys(modeIds).join(', ')}`,
        )
      }

      let value = rawValue

      // Convert hex strings to Figma RGBA for COLOR type
      if (token.type === 'COLOR' && typeof rawValue === 'string' && rawValue.startsWith('#')) {
        value = hexToFigmaColor(rawValue)
      }

      variable.setValueForMode(modeId, value)
    }

    // Set scopes (default: empty array = hidden from property pickers / primitives)
    variable.scopes = token.scopes || []

    // Set code syntax per platform
    if (token.codeSyntax) {
      if (token.codeSyntax.WEB) {
        variable.setVariableCodeSyntax('WEB', token.codeSyntax.WEB)
      }
      if (token.codeSyntax.ANDROID) {
        variable.setVariableCodeSyntax('ANDROID', token.codeSyntax.ANDROID)
      }
      if (token.codeSyntax.iOS) {
        variable.setVariableCodeSyntax('iOS', token.codeSyntax.iOS)
      }
    }

    variables[token.name] = variable
  }

  return { variables }
}

/**
 * Converts a hex color string to a Figma RGBA object.
 * Supports "#rgb", "#rrggbb", and "#rrggbbaa".
 *
 * @param {string} hex
 * @returns {{ r: number, g: number, b: number, a: number }}
 */
function hexToFigmaColor(hex) {
  let h = hex.replace('#', '')

  // Expand shorthand #rgb → #rrggbb
  if (h.length === 3) {
    h = h
      .split('')
      .map((c) => c + c)
      .join('')
  }

  const r = parseInt(h.substring(0, 2), 16) / 255
  const g = parseInt(h.substring(2, 4), 16) / 255
  const b = parseInt(h.substring(4, 6), 16) / 255
  const a = h.length === 8 ? parseInt(h.substring(6, 8), 16) / 255 : 1

  return { r, g, b, a }
}

/**
 * createComponentWithVariants
 *
 * Creates a component set by generating all combinations of `variantAxes`,
 * building one Figma component per combination, then calling
 * `figma.combineAsVariants` to produce the component set. After combining,
 * the variants are repositioned into a grid so they don't all stack at (0, 0).
 *
 * @param {{
 *   name: string,
 *   description?: string,
 *   variantAxes: Record<string, string[]>,
 *   baseProps: {
 *     width: number,
 *     height: number,
 *     fills?: Paint[],
 *     padding?: {top?: number, bottom?: number, left?: number, right?: number},
 *     radius?: number,
 *     layoutMode?: 'HORIZONTAL' | 'VERTICAL' | 'NONE',
 *     itemSpacing?: number
 *   },
 *   page: PageNode
 * }} config
 *   - `name`: Component set name (e.g. "Button").
 *   - `description`: Optional human-readable purpose and usage guidance.
 *   - `variantAxes`: Each key is a variant property name; each value is an array of
 *     allowed values. All combinations are generated (Cartesian product).
 *     Example: { Size: ['Small', 'Medium', 'Large'], Style: ['Primary', 'Ghost'] }
 *     produces 6 variants.
 *   - `baseProps`: Visual properties applied to every variant.
 *   - `page`: The PageNode to create components on (must be set as current page by caller).
 * @returns {Promise<{
 *   componentSet: ComponentSetNode,
 *   variants: ComponentNode[]
 * }>}
 */
async function createComponentWithVariants(config) {
  const { name, variantAxes, baseProps, page } = config

  // Ensure we are on the correct page
  await figma.setCurrentPageAsync(page)

  // Compute Cartesian product of variant axes
  const axisNames = Object.keys(variantAxes)
  const axisValues = axisNames.map((k) => variantAxes[k])
  const combinations = cartesianProduct(axisValues)

  // Build one component per combination
  const components = []
  for (const combo of combinations) {
    const comp = figma.createComponent()

    // Name: "Property=Value, Property=Value, ..."
    comp.name = axisNames.map((ax, i) => `${ax}=${combo[i]}`).join(', ')

    // Base geometry
    comp.resize(baseProps.width, baseProps.height)

    // Fills
    if (baseProps.fills !== undefined) {
      comp.fills = baseProps.fills
    } else {
      comp.fills = [{ type: 'SOLID', color: { r: 0.9, g: 0.9, b: 0.9 } }]
    }

    // Corner radius
    if (baseProps.radius !== undefined) {
      comp.cornerRadius = baseProps.radius
    }

    // Auto-layout
    if (baseProps.layoutMode && baseProps.layoutMode !== 'NONE') {
      comp.layoutMode = baseProps.layoutMode
      comp.primaryAxisAlignItems = 'CENTER'
      comp.counterAxisAlignItems = 'CENTER'
      if (baseProps.itemSpacing !== undefined) {
        comp.itemSpacing = baseProps.itemSpacing
      }
    }

    // Padding
    if (baseProps.padding) {
      comp.paddingTop = baseProps.padding.top ?? 0
      comp.paddingBottom = baseProps.padding.bottom ?? 0
      comp.paddingLeft = baseProps.padding.left ?? 0
      comp.paddingRight = baseProps.padding.right ?? 0
    }

    page.appendChild(comp)
    components.push(comp)
  }

  // Combine into a component set
  const componentSet = figma.combineAsVariants(components, page)
  componentSet.name = name
  if (config.description) {
    componentSet.description = config.description
  }

  // Grid layout — variants stack at (0, 0) after combineAsVariants; reposition them.
  const GRID_GAP = 16
  const cols = Math.max(1, axisValues[axisValues.length - 1]?.length ?? 1)
  const variantWidth = baseProps.width
  const variantHeight = baseProps.height

  componentSet.children.forEach((variant, idx) => {
    const col = idx % cols
    const row = Math.floor(idx / cols)
    variant.x = col * (variantWidth + GRID_GAP)
    variant.y = row * (variantHeight + GRID_GAP)
  })

  // Resize component set to wrap its children with padding
  const totalCols = Math.min(cols, combinations.length)
  const totalRows = Math.ceil(combinations.length / cols)
  const PADDING = 40
  componentSet.resize(
    totalCols * variantWidth + (totalCols - 1) * GRID_GAP + PADDING * 2,
    totalRows * variantHeight + (totalRows - 1) * GRID_GAP + PADDING * 2,
  )

  // Position component set at a safe canvas location
  componentSet.x = 480
  componentSet.y = 80

  return { componentSet, variants: componentSet.children }
}

/**
 * Computes the Cartesian product of multiple arrays.
 * cartesianProduct([[A, B], [1, 2]]) → [[A,1], [A,2], [B,1], [B,2]]
 *
 * @param {Array<string[]>} arrays
 * @returns {string[][]}
 */
function cartesianProduct(arrays) {
  return arrays.reduce(
    (acc, curr) => acc.flatMap((combo) => curr.map((val) => [...combo, val])),
    [[]],
  )
}

const ICONS={"Workflow": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"20\" height=\"20\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"#63676F\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"lucide lucide-workflow\" aria-hidden=\"true\"><rect width=\"8\" height=\"8\" x=\"3\" y=\"3\" rx=\"2\"></rect><path d=\"M7 11v4a2 2 0 0 0 2 2h4\"></path><rect width=\"8\" height=\"8\" x=\"13\" y=\"13\" rx=\"2\"></rect></svg>", "Search": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"20\" height=\"20\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"#63676F\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"lucide lucide-search\" aria-hidden=\"true\"><path d=\"m21 21-4.34-4.34\"></path><circle cx=\"11\" cy=\"11\" r=\"8\"></circle></svg>", "ChevronDown": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"20\" height=\"20\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"#63676F\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"lucide lucide-chevron-down\" aria-hidden=\"true\"><path d=\"m6 9 6 6 6-6\"></path></svg>", "Settings2": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"20\" height=\"20\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"#63676F\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"lucide lucide-settings-2\" aria-hidden=\"true\"><path d=\"M14 17H5\"></path><path d=\"M19 7h-9\"></path><circle cx=\"17\" cy=\"17\" r=\"3\"></circle><circle cx=\"7\" cy=\"7\" r=\"3\"></circle></svg>", "FileText": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"20\" height=\"20\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"#63676F\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"lucide lucide-file-text\" aria-hidden=\"true\"><path d=\"M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z\"></path><path d=\"M14 2v5a1 1 0 0 0 1 1h5\"></path><path d=\"M10 9H8\"></path><path d=\"M16 13H8\"></path><path d=\"M16 17H8\"></path></svg>", "ArrowUpRight": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"20\" height=\"20\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"#63676F\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"lucide lucide-arrow-up-right\" aria-hidden=\"true\"><path d=\"M7 7h10v10\"></path><path d=\"M7 17 17 7\"></path></svg>", "PanelRight": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"20\" height=\"20\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"#63676F\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"lucide lucide-panel-right\" aria-hidden=\"true\"><rect width=\"18\" height=\"18\" x=\"3\" y=\"3\" rx=\"2\"></rect><path d=\"M15 3v18\"></path></svg>", "Clock3": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"20\" height=\"20\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"#63676F\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"lucide lucide-clock-3\" aria-hidden=\"true\"><circle cx=\"12\" cy=\"12\" r=\"10\"></circle><path d=\"M12 6v6h4\"></path></svg>", "ShieldCheck": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"20\" height=\"20\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"#63676F\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"lucide lucide-shield-check\" aria-hidden=\"true\"><path d=\"M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z\"></path><path d=\"m9 12 2 2 4-4\"></path></svg>", "CircleCheck": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"20\" height=\"20\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"#63676F\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"lucide lucide-circle-check lucide-check-circle-2\" aria-hidden=\"true\"><circle cx=\"12\" cy=\"12\" r=\"10\"></circle><path d=\"m16 9-5.5 5.5L8 12\"></path></svg>", "Pause": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"20\" height=\"20\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"#63676F\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"lucide lucide-pause\" aria-hidden=\"true\"><rect x=\"14\" y=\"3\" width=\"5\" height=\"18\" rx=\"1\"></rect><rect x=\"5\" y=\"3\" width=\"5\" height=\"18\" rx=\"1\"></rect></svg>", "Maximize2": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"20\" height=\"20\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"#63676F\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"lucide lucide-maximize-2\" aria-hidden=\"true\"><path d=\"M15 3h6v6\"></path><path d=\"m21 3-7 7\"></path><path d=\"m3 21 7-7\"></path><path d=\"M9 21H3v-6\"></path></svg>", "Plus": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"20\" height=\"20\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"#63676F\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"lucide lucide-plus\" aria-hidden=\"true\"><path d=\"M5 12h14\"></path><path d=\"M12 5v14\"></path></svg>", "X": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"20\" height=\"20\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"#63676F\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"lucide lucide-x\" aria-hidden=\"true\"><path d=\"M18 6 6 18\"></path><path d=\"m6 6 12 12\"></path></svg>", "GitBranch": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"20\" height=\"20\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"#63676F\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"lucide lucide-git-branch\" aria-hidden=\"true\"><path d=\"M15 6a9 9 0 0 0-9 9V3\"></path><circle cx=\"18\" cy=\"6\" r=\"3\"></circle><circle cx=\"6\" cy=\"18\" r=\"3\"></circle></svg>", "CreditCard": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"20\" height=\"20\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"#63676F\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"lucide lucide-credit-card\" aria-hidden=\"true\"><rect width=\"20\" height=\"14\" x=\"2\" y=\"5\" rx=\"2\"></rect><line x1=\"2\" x2=\"22\" y1=\"10\" y2=\"10\"></line><path d=\"M6 14h2\"></path></svg>", "Activity": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"20\" height=\"20\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"#63676F\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"lucide lucide-activity\" aria-hidden=\"true\"><path d=\"M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2\"></path></svg>", "Database": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"20\" height=\"20\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"#63676F\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"lucide lucide-database\" aria-hidden=\"true\"><ellipse cx=\"12\" cy=\"5\" rx=\"9\" ry=\"3\"></ellipse><path d=\"M3 5V19A9 3 0 0 0 21 19V5\"></path><path d=\"M3 12A9 3 0 0 0 21 12\"></path></svg>", "Layers": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"20\" height=\"20\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"#63676F\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"lucide lucide-layers lucide-layers-3\" aria-hidden=\"true\"><path d=\"M12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83z\"></path><path d=\"M2 12a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 12\"></path><path d=\"M2 17a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 17\"></path></svg>", "MoreHorizontal": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"20\" height=\"20\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"#63676F\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"lucide lucide-ellipsis lucide-more-horizontal\" aria-hidden=\"true\"><circle cx=\"12\" cy=\"12\" r=\"1\"></circle><circle cx=\"19\" cy=\"12\" r=\"1\"></circle><circle cx=\"5\" cy=\"12\" r=\"1\"></circle></svg>", "Keyboard": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"20\" height=\"20\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"#63676F\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"lucide lucide-keyboard\" aria-hidden=\"true\"><path d=\"M10 8h.01\"></path><path d=\"M12 12h.01\"></path><path d=\"M14 8h.01\"></path><path d=\"M16 12h.01\"></path><path d=\"M18 8h.01\"></path><path d=\"M6 8h.01\"></path><path d=\"M7 16h10\"></path><path d=\"M8 12h.01\"></path><rect width=\"20\" height=\"16\" x=\"2\" y=\"4\" rx=\"2\"></rect></svg>", "Code": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"20\" height=\"20\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"#63676F\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"lucide lucide-code\" aria-hidden=\"true\"><path d=\"m16 18 6-6-6-6\"></path><path d=\"m8 6-6 6 6 6\"></path></svg>", "ZoomIn": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"20\" height=\"20\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"#63676F\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"lucide lucide-zoom-in\" aria-hidden=\"true\"><circle cx=\"11\" cy=\"11\" r=\"8\"></circle><line x1=\"21\" x2=\"16.65\" y1=\"21\" y2=\"16.65\"></line><line x1=\"11\" x2=\"11\" y1=\"8\" y2=\"14\"></line><line x1=\"8\" x2=\"14\" y1=\"11\" y2=\"11\"></line></svg>", "ZoomOut": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"20\" height=\"20\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"#63676F\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"lucide lucide-zoom-out\" aria-hidden=\"true\"><circle cx=\"11\" cy=\"11\" r=\"8\"></circle><line x1=\"21\" x2=\"16.65\" y1=\"21\" y2=\"16.65\"></line><line x1=\"8\" x2=\"14\" y1=\"11\" y2=\"11\"></line></svg>", "Check": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"20\" height=\"20\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"#63676F\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"lucide lucide-check\" aria-hidden=\"true\"><path d=\"M20 6 9 17l-5-5\"></path></svg>", "CircleDashed": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"20\" height=\"20\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"#63676F\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"lucide lucide-circle-dashed\" aria-hidden=\"true\"><path d=\"M10.1 2.182a10 10 0 0 1 3.8 0\"></path><path d=\"M13.9 21.818a10 10 0 0 1-3.8 0\"></path><path d=\"M17.609 3.721a10 10 0 0 1 2.69 2.7\"></path><path d=\"M2.182 13.9a10 10 0 0 1 0-3.8\"></path><path d=\"M20.279 17.609a10 10 0 0 1-2.7 2.69\"></path><path d=\"M21.818 10.1a10 10 0 0 1 0 3.8\"></path><path d=\"M3.721 6.391a10 10 0 0 1 2.7-2.69\"></path><path d=\"M6.391 20.279a10 10 0 0 1-2.69-2.7\"></path></svg>", "ChevronRight": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"20\" height=\"20\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"#63676F\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"lucide lucide-chevron-right\" aria-hidden=\"true\"><path d=\"m9 18 6-6-6-6\"></path></svg>", "CircleHelp": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"20\" height=\"20\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"#63676F\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"lucide lucide-circle-question-mark lucide-help-circle lucide-circle-help\" aria-hidden=\"true\"><circle cx=\"12\" cy=\"12\" r=\"10\"></circle><path d=\"M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3\"></path><path d=\"M12 17h.01\"></path></svg>"};

if(figma.currentPage.children.some(n=>n.name==='01 · Workflow / Overview')) throw new Error('Review already exists; inspect state ledger before mutating.');
const fonts=[{family:'Inter',style:'Regular'},{family:'Inter',style:'Medium'},{family:'Inter',style:'Semi Bold'},{family:'JetBrains Mono',style:'Regular'}];
await Promise.all(fonts.map(f=>figma.loadFontAsync(f)));
const imports={surface:'a4865545b526a5b3399a512667f40c9efe0c2fc4',chrome:'3fe6117980bb52e96ac3ed63a40765746e689874',ink:'cf92d4e8c6a5a5ed82f024d47d11c21d5162ac3c',muted:'3184ed9d395b6588f571919557ce051337792211',line:'b146978dd976855f9098c55f47eaf146f5631994',waitbg:'cd659deee41bf6d6cc97eec308abb44b05095d47',waitink:'613d8c90cd590fbf31d5657f216aa04240d960e8',good:'1975fcd9ea85214a919b9125c8d137571058106a',bad:'78719d7b2fb3e82402ce90c53b1d7212d495a0a2',space4:'6991c8db166da9c4d23de28830fc570f19aba2e9',space8:'15bb1c0f339146e931cf0dc15f89ed57dcbd907e',space12:'fabe3eb617318c0a59ce59bbea8eebdf1fa7d14c',space16:'16bc6f84b6e7e20e4234ef79030ee580ec0f4505',space24:'be3115966ea99eef888c9f25751b54695c7e88d2'};
const remote=Object.fromEntries(await Promise.all(Object.entries(imports).map(async([k,v])=>[k,await figma.variables.importVariableByKeyAsync(v)])));
const {collection,modeIds}=await createVariableCollection('SwarmCircuit / Console',['Light']);
const own={canvas:['#FAFAF9','#141516'],accent:['#415CC7','#9CAEFF'],selected:['#EEF1FC','#272E46'],edge:['#ADB2BD','#696F7B'],goodbg:['#EDF5EF','#20372A'],dangerbg:['#FAEDEE','#3C2529'],focus:['#415CC7','#A7B9FF']};
const prim=await createSemanticTokens(collection,modeIds,Object.entries(own).map(([n,v])=>({name:'primitive/'+n,type:'COLOR',values:{Light:v[0]},scopes:[]})));
const dark={surface:'#1C1D20',chrome:'#17181A',ink:'#F0F0F2',muted:'#A8ABB3',line:'#36383D',waitbg:'#352C1E',waitink:'#E6BE70',good:'#9EC9AC',bad:'#E8A1A9'};
const spec=Object.entries(imports).map(([n])=>({name:n,type:n.startsWith('space')?'FLOAT':'COLOR',values:{Light:{type:'VARIABLE_ALIAS',id:remote[n].id},Dark:n.startsWith('space')?{type:'VARIABLE_ALIAS',id:remote[n].id}:dark[n]},scopes:n.startsWith('space')?['GAP']:n==='line'?['STROKE_COLOR']:['FRAME_FILL','SHAPE_FILL','TEXT_FILL','STROKE_COLOR'],codeSyntax:{WEB:'var(--sc-'+n+')'}}));
for(const n of Object.keys(own))spec.push({name:n,type:'COLOR',values:{Light:{type:'VARIABLE_ALIAS',id:prim.variables['primitive/'+n].id},Dark:{type:'VARIABLE_ALIAS',id:prim.variables['primitive/'+n].id}},scopes:['FRAME_FILL','SHAPE_FILL','TEXT_FILL','STROKE_COLOR'],codeSyntax:{WEB:'var(--sc-'+n+')'}});
for(const token of spec)delete token.values.Dark;
const {variables:V}=await createSemanticTokens(collection,modeIds,spec);
const styles={};for(const [name,size,line,font] of [['Body',14,20,'Regular'],['Label',13,18,'Medium'],['Caption',12,18,'Regular'],['Title',22,30,'Semi Bold'],['Section',16,24,'Semi Bold'],['Mono',11,16,'Regular']]){const s=figma.createTextStyle();s.name='Console/'+name;s.fontName={family:name==='Mono'?'JetBrains Mono':'Inter',style:font};s.fontSize=size;s.lineHeight={unit:'PIXELS',value:line};styles[name]=s;}
const paint=n=>figma.variables.setBoundVariableForPaint({type:'SOLID',color:{r:0,g:0,b:0}},'color',V[n]);
function text(value,style='Body',color='ink',width){const n=figma.createText();n.name=value;n.fontName=styles[style].fontName;n.textStyleId=styles[style].id;n.characters=value;n.fills=[paint(color)];if(width){n.textAutoResize='HEIGHT';n.resize(width,n.height);}return n;}
function row(parent,name,width,height,dir='HORIZONTAL',gap='space8',bg){const n=figma.createAutoLayout(dir);n.name=name;n.resize(width,height);n.primaryAxisSizingMode='FIXED';n.counterAxisSizingMode='FIXED';n.counterAxisAlignItems=dir==='HORIZONTAL'?'CENTER':'MIN';n.fills=bg?[paint(bg)]:[];n.setBoundVariable('itemSpacing',V[gap]);if(parent)parent.appendChild(n);return n;}
const family=await createComponentWithVariants({name:'Console / Task node',description:'Read-only task evidence. Node color is supporting status information; text and icon always remain visible. Selected state uses focus blue. Port direction is prerequisite to dependent, never an editing affordance.',variantAxes:{State:['Complete','Waiting','Selected','Neutral']},baseProps:{width:188,height:134,layoutMode:'VERTICAL',padding:{top:16,bottom:16,left:16,right:16},itemSpacing:12,radius:10},page:figma.currentPage});
const nodeProps={};const p={title:family.componentSet.addComponentProperty('Title','TEXT','Request dataset\naccess'),owner:family.componentSet.addComponentProperty('Owner','TEXT','Researcher'),status:family.componentSet.addComponentProperty('Status','TEXT','Waiting for human')};for(const comp of family.variants){comp.primaryAxisAlignItems='MIN';comp.counterAxisAlignItems='MIN';comp.fills=[paint('surface')];comp.strokes=[paint(comp.name.includes('Selected')?'accent':'line')];comp.strokeWeight=comp.name.includes('Selected')?1.5:1;for(const p of ['paddingLeft','paddingRight','paddingTop','paddingBottom'])comp.setBoundVariable(p,V.space16);comp.setBoundVariable('itemSpacing',V.space12);const head=row(comp,'Task identity',156,20);const icon=figma.createNodeFromSvg(ICONS[comp.name.includes('Complete')?'CircleCheck':'ShieldCheck']);icon.resize(18,18);head.appendChild(icon);const owner=text('Researcher','Caption','muted');head.appendChild(owner);const title=text('Request dataset\naccess','Label','ink',156);comp.appendChild(title);const state=text(comp.name.includes('Complete')?'Completed':'Waiting for human','Caption',comp.name.includes('Complete')?'good':'waitink');comp.appendChild(state);title.componentPropertyReferences={characters:p.title};owner.componentPropertyReferences={characters:p.owner};state.componentPropertyReferences={characters:p.status};nodeProps[comp.name]=p;}
family.componentSet.x=200;family.componentSet.y=3000;
figma.currentPage.name='Console · Design review';
return {createdNodeIds:family.componentSet.findAll(()=>true).map(n=>n.id).concat(family.componentSet.id),componentSetId:family.componentSet.id,nodeProps,variants:family.variants.map(n=>({id:n.id,name:n.name})),collectionId:collection.id,modes:modeIds,variables:Object.fromEntries(Object.entries(V).map(([n,v])=>[n,v.id])),styles:Object.fromEntries(Object.entries(styles).map(([n,s])=>[n,s.id])),primitiveIds:Object.values(prim.variables).map(v=>v.id),counts:{variables:Object.keys(V).length,taskStates:family.variants.length}};
