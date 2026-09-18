---
version: alpha
name: Xiaohongshu-design-analysis
description: "A bright, content-first visual system built on clean white surfaces, near-black typography, restrained neutral grays, and Xiaohongshu's vivid red as the single dominant brand accent. The design language feels youthful, social, tactile, and editorial rather than corporate: imagery carries most of the visual energy, interfaces stay quiet around content, rounded forms soften controls and cards, and red is reserved for identity, emphasis, selection, and high-priority actions. Density is moderate, hierarchy is direct, and decorative effects remain subtle so photography, video, avatars, titles, and social metadata stay visually dominant. This is an unofficial observation-based design analysis, not Xiaohongshu's internal design system."

colors:
  primary: "#FF2442"
  on-primary: "#FFFFFF"
  primary-hover: "#F20D32"
  primary-pressed: "#D90B2C"
  primary-soft: "#FFF1F3"
  primary-border: "#FFD6DC"
  ink: "#1A1A1A"
  ink-secondary: "#666666"
  ink-tertiary: "#999999"
  ink-disabled: "#B8B8B8"
  canvas: "#FFFFFF"
  surface: "#FFFFFF"
  surface-soft: "#F7F7F7"
  surface-muted: "#FAFAFA"
  surface-hover: "#F5F5F5"
  surface-active: "#F0F0F0"
  hairline: "#EDEDED"
  hairline-strong: "#DDDDDD"
  overlay: "rgba(0,0,0,0.48)"
  inverse-canvas: "#1A1A1A"
  inverse-ink: "#FFFFFF"
  semantic-success: "#1FA463"
  semantic-warning: "#E89A19"
  semantic-error: "#E5484D"
  semantic-info: "#3E7BFA"

typography:
  display-xl:
    fontFamily: "PingFang SC, Microsoft YaHei, Noto Sans CJK SC, system-ui, sans-serif"
    fontSize: 40px
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: -0.5px
  display-lg:
    fontFamily: "PingFang SC, Microsoft YaHei, Noto Sans CJK SC, system-ui, sans-serif"
    fontSize: 32px
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: -0.3px
  heading-lg:
    fontFamily: "PingFang SC, Microsoft YaHei, Noto Sans CJK SC, system-ui, sans-serif"
    fontSize: 24px
    fontWeight: 600
    lineHeight: 1.35
    letterSpacing: 0
  heading-md:
    fontFamily: "PingFang SC, Microsoft YaHei, Noto Sans CJK SC, system-ui, sans-serif"
    fontSize: 20px
    fontWeight: 600
    lineHeight: 1.4
    letterSpacing: 0
  heading-sm:
    fontFamily: "PingFang SC, Microsoft YaHei, Noto Sans CJK SC, system-ui, sans-serif"
    fontSize: 16px
    fontWeight: 600
    lineHeight: 1.45
    letterSpacing: 0
  body-lg:
    fontFamily: "PingFang SC, Microsoft YaHei, Noto Sans CJK SC, system-ui, sans-serif"
    fontSize: 16px
    fontWeight: 400
    lineHeight: 1.6
    letterSpacing: 0
  body:
    fontFamily: "PingFang SC, Microsoft YaHei, Noto Sans CJK SC, system-ui, sans-serif"
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.55
    letterSpacing: 0
  body-medium:
    fontFamily: "PingFang SC, Microsoft YaHei, Noto Sans CJK SC, system-ui, sans-serif"
    fontSize: 14px
    fontWeight: 500
    lineHeight: 1.55
    letterSpacing: 0
  body-sm:
    fontFamily: "PingFang SC, Microsoft YaHei, Noto Sans CJK SC, system-ui, sans-serif"
    fontSize: 13px
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: 0
  caption:
    fontFamily: "PingFang SC, Microsoft YaHei, Noto Sans CJK SC, system-ui, sans-serif"
    fontSize: 12px
    fontWeight: 400
    lineHeight: 1.45
    letterSpacing: 0
  button:
    fontFamily: "PingFang SC, Microsoft YaHei, Noto Sans CJK SC, system-ui, sans-serif"
    fontSize: 14px
    fontWeight: 500
    lineHeight: 1.2
    letterSpacing: 0
  metric:
    fontFamily: "Inter, PingFang SC, system-ui, sans-serif"
    fontSize: 24px
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: -0.2px

rounded:
  xs: 4px
  sm: 6px
  md: 8px
  lg: 12px
  xl: 16px
  xxl: 20px
  pill: 9999px
  full: 9999px

spacing:
  xxs: 4px
  xs: 8px
  sm: 12px
  md: 16px
  lg: 20px
  xl: 24px
  xxl: 32px
  xxxl: 40px
  section: 48px

components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    typography: "{typography.button}"
    rounded: "{rounded.sm}"
    padding: "9px 16px"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
    textColor: "{colors.on-primary}"
    typography: "{typography.button}"
    rounded: "{rounded.sm}"
  button-primary-pressed:
    backgroundColor: "{colors.primary-pressed}"
    textColor: "{colors.on-primary}"
    typography: "{typography.button}"
    rounded: "{rounded.sm}"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    borderColor: "{colors.hairline-strong}"
    typography: "{typography.button}"
    rounded: "{rounded.sm}"
    padding: "9px 16px"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.ink-secondary}"
    typography: "{typography.button}"
    rounded: "{rounded.sm}"
    padding: "9px 12px"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    borderColor: "{colors.hairline-strong}"
    typography: "{typography.body}"
    rounded: "{rounded.sm}"
    padding: "9px 12px"
  search-field:
    backgroundColor: "{colors.surface-soft}"
    textColor: "{colors.ink}"
    borderColor: "transparent"
    typography: "{typography.body}"
    rounded: "{rounded.pill}"
    padding: "9px 16px"
  content-card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
  media-card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
  tag-neutral:
    backgroundColor: "{colors.surface-soft}"
    textColor: "{colors.ink-secondary}"
    typography: "{typography.caption}"
    rounded: "{rounded.pill}"
    padding: "4px 8px"
  tag-primary:
    backgroundColor: "{colors.primary-soft}"
    textColor: "{colors.primary}"
    typography: "{typography.caption}"
    rounded: "{rounded.pill}"
    padding: "4px 8px"
  avatar:
    rounded: "{rounded.full}"
  dialog:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
    padding: "24px"
---

# Xiaohongshu DESIGN.md

> Unofficial, observation-based design analysis derived from Xiaohongshu's public-facing visual language. It is not an official Xiaohongshu design system and does not claim access to internal design tokens, Figma libraries, or proprietary implementation details.

## 1. Visual Theme & Atmosphere

Xiaohongshu's visual language is bright, social, image-led, youthful, and intentionally lightweight. The interface rarely competes with content. White and very light neutral surfaces create a quiet frame around vivid photography, video, avatars, titles, reactions, and social metadata.

The system is recognizable less through ornamental styling than through a specific balance:

- High-energy content inside low-noise UI chrome.
- Strong red branding used selectively rather than everywhere.
- Soft rounded geometry without exaggerated SaaS-style pillification.
- Short, direct typographic hierarchy.
- Friendly spacing with moderate density.
- Minimal elevation and restrained shadows.
- Strong visual emphasis on media and human identity.
- Clear social interaction states.

The design should feel approachable and contemporary, not luxurious, technical, corporate, or futuristic.

### Atmosphere keywords

- Bright
- Social
- Youthful
- Content-first
- Friendly
- Editorial
- Lightweight
- Direct
- Visual
- Energetic

### Core principle

**Content carries the color; interface carries the structure.**

The UI should remain visually quieter than the photos, covers, videos, avatars, and user-generated content it presents.

---

## 2. Color Palette & Roles

### Brand red

The most recognizable chromatic signal is a vivid warm red.

| Token | Value | Role |
|---|---|---|
| `primary` | `#FF2442` | Brand identity, primary emphasis, selected states, highest-priority actions |
| `primary-hover` | `#F20D32` | Hover state |
| `primary-pressed` | `#D90B2C` | Pressed state |
| `primary-soft` | `#FFF1F3` | Soft selected state, subtle branded surface |
| `primary-border` | `#FFD6DC` | Soft accent border |
| `on-primary` | `#FFFFFF` | Text/icons on red |

The primary red should behave as a signal, not as a background system.

### Neutral surfaces

| Token | Value | Role |
|---|---|---|
| `canvas` | `#FFFFFF` | Primary page/background canvas |
| `surface` | `#FFFFFF` | Cards, controls, containers |
| `surface-soft` | `#F7F7F7` | Search fields, secondary containers |
| `surface-muted` | `#FAFAFA` | Very soft grouped regions |
| `surface-hover` | `#F5F5F5` | Hover feedback |
| `surface-active` | `#F0F0F0` | Pressed/active feedback |
| `hairline` | `#EDEDED` | Fine dividers |
| `hairline-strong` | `#DDDDDD` | Inputs and stronger boundaries |

### Text neutrals

| Token | Value | Role |
|---|---|---|
| `ink` | `#1A1A1A` | Primary text |
| `ink-secondary` | `#666666` | Metadata and secondary text |
| `ink-tertiary` | `#999999` | Timestamps, placeholders, tertiary information |
| `ink-disabled` | `#B8B8B8` | Disabled states |

Avoid pure black for large areas of UI. Near-black produces a softer visual contrast against white.

### Semantic colors

Semantic colors should remain distinct from the brand red:

- Success: `#1FA463`
- Warning: `#E89A19`
- Error: `#E5484D`
- Info: `#3E7BFA`

Do not use the brand red for every error, alert, delete action, or negative state. Brand meaning and semantic meaning should remain separable.

### Color behavior

Do:

- Use red for the strongest intentional emphasis.
- Let imagery supply most high-saturation color.
- Use white and neutral gray for structure.
- Use soft tinted red backgrounds for selected or lightly branded states.

Don't:

- Use red as the default page background.
- Make every interactive control red.
- Combine red with unrelated neon accents.
- Use heavy gradients as a default visual motif.

---

## 3. Typography Rules

### Typeface character

The system favors neutral modern sans-serif typography. It should feel native, readable, compact, and visually quiet.

Recommended stack:

```css
font-family: "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
```

For Latin-heavy metrics or numerals, Inter or system UI fonts can be used as a fallback.

### Hierarchy

| Style | Size | Weight | Line Height | Character |
|---|---:|---:|---:|---|
| Display XL | 40px | 600 | 1.20 | Rare, strong title moments |
| Display LG | 32px | 600 | 1.25 | Major heading |
| Heading LG | 24px | 600 | 1.35 | Strong section heading |
| Heading MD | 20px | 600 | 1.40 | Standard heading |
| Heading SM | 16px | 600 | 1.45 | Compact heading/card title |
| Body LG | 16px | 400 | 1.60 | Comfortable reading text |
| Body | 14px | 400 | 1.55 | Default UI/body text |
| Body Medium | 14px | 500 | 1.55 | Emphasized body text |
| Body SM | 13px | 400 | 1.50 | Dense metadata |
| Caption | 12px | 400 | 1.45 | Auxiliary metadata |

### Typography behavior

- Favor semibold (`600`) over very heavy bold weights.
- Keep UI copy short and direct.
- Use strong hierarchy through size and weight, not color proliferation.
- Use secondary gray for metadata rather than shrinking text excessively.
- Chinese text should maintain comfortable line-height.
- Avoid serif type as a system-wide default.
- Avoid highly stylized display fonts in functional UI.

### Titles

Titles should feel conversational and direct rather than editorially formal. Strong titles usually use dark text on a clean surface with little decoration.

### Numbers

For counts, statistics, and metrics:

- Prefer tabular numerals where alignment matters.
- Use weight 500–600.
- Avoid oversized numbers unless they are the true focal point.

---

## 4. Shape Language & Corner Radius

Xiaohongshu's shape language is soft but not cartoonishly round.

| Token | Radius | Typical role |
|---|---:|---|
| `xs` | 4px | Compact labels and small controls |
| `sm` | 6px | Buttons, inputs |
| `md` | 8px | Cards and dropdowns |
| `lg` | 12px | Media containers, dialogs |
| `xl` | 16px | Large soft containers |
| `xxl` | 20px | Occasional large visual surfaces |
| `pill` | 9999px | Search fields, chips, compact selectors |
| `full` | 9999px | Avatars and circular controls |

### Radius behavior

- Media may use slightly larger radii than text controls.
- Pills are appropriate for compact filters, search surfaces, tags, and social interaction controls.
- Standard cards should not automatically use 20–32px radius.
- Maintain consistent radius families across related components.

---

## 5. Spacing Scale

Use a 4px base unit.

| Token | Value |
|---|---:|
| `xxs` | 4px |
| `xs` | 8px |
| `sm` | 12px |
| `md` | 16px |
| `lg` | 20px |
| `xl` | 24px |
| `xxl` | 32px |
| `xxxl` | 40px |
| `section` | 48px |

### Spacing character

- Icon + label: typically 6–8px.
- Related text lines: 4–8px.
- Compact control groups: 8–12px.
- Card internal spacing: 12–20px.
- Larger content groups: 24–32px.
- Major visual sections: 32–48px.

The system should feel breathable without becoming sparse or luxurious.

---

## 6. Component Stylings

### 6.1 Primary Buttons

Primary buttons carry the brand red.

```yaml
background: '#FF2442'
text: '#FFFFFF'
radius: 6px
font-size: 14px
font-weight: 500
padding: 9px 16px
```

Behavior:

- Hover deepens red slightly.
- Pressed state deepens further.
- Disabled state loses saturation and contrast.
- Avoid adding large shadows.

Use primary buttons selectively so the red remains meaningful.

### 6.2 Secondary Buttons

```yaml
background: '#FFFFFF'
text: '#1A1A1A'
border: '1px solid #DDDDDD'
radius: 6px
```

Secondary buttons should appear calm and structural.

### 6.3 Ghost Buttons

Ghost controls use transparent backgrounds and neutral text. Hover introduces a soft gray surface.

They should feel lightweight and disappear visually when idle.

### 6.4 Icon Buttons

- Neutral gray icon by default.
- Soft gray hover background.
- Round or softly rounded hit area.
- Red only when the action is selected, liked, followed, favorited, or otherwise brand-significant.

### 6.5 Inputs

Inputs favor a quiet border and clean white surface.

```yaml
background: '#FFFFFF'
border: '1px solid #DDDDDD'
text: '#1A1A1A'
placeholder: '#999999'
radius: 6px
```

Focus states should be visible but lightweight. A red border or soft red focus ring is appropriate.

### 6.6 Search Fields

Search fields may be visually softer than standard inputs:

```yaml
background: '#F7F7F7'
border: transparent
radius: pill
```

The field should feel integrated into the surface rather than boxed in.

### 6.7 Cards

Cards are usually simple containers around content rather than heavily elevated objects.

Default card character:

- White background.
- Minimal or no shadow.
- Optional thin neutral border.
- 8–12px radius.
- Content determines height.
- Media often dominates card area.

### 6.8 Media Cards

Media cards should prioritize the visual asset.

- Image/video uses full available width.
- `object-fit: cover` when cropping is needed.
- 8–12px radius.
- Text hierarchy remains visually secondary to the image.
- Overlay controls should be subtle and temporary.

### 6.9 Tags & Chips

Neutral chip:

```yaml
background: '#F7F7F7'
text: '#666666'
radius: pill
padding: 4px 8px
```

Branded chip:

```yaml
background: '#FFF1F3'
text: '#FF2442'
radius: pill
padding: 4px 8px
```

Use solid-red chips sparingly.

### 6.10 Avatars

Avatars are circular and visually important. They establish social identity and should not be visually buried under surrounding chrome.

Common sizes:

- 24px compact
- 32px standard
- 40px prominent
- 48–64px profile emphasis

### 6.11 Navigation

Navigation should remain visually calm.

Default:

- Neutral text/icon.
- Transparent background.

Hover:

- Soft gray background or darker text.

Selected:

- Red text/icon, soft red surface, underline, or small indicator.
- Prefer one or two selection signals, not all at once.

### 6.12 Tabs

Tabs use clear text hierarchy and minimal chrome.

Common selected treatment:

- Dark or red label.
- Stronger font weight.
- 2px red indicator or subtle red emphasis.

Avoid turning every tab into a solid-red pill.

### 6.13 Dropdowns & Popovers

- White surface.
- 8px radius.
- Thin neutral border or soft shadow.
- Compact vertical spacing.
- Hover uses soft gray.
- Selected items may use soft red + red text.

### 6.14 Dialogs

- White surface.
- 12px radius.
- Soft but visible elevation.
- Clear title/body/action hierarchy.
- Backdrop uses neutral black transparency.

Do not make modal surfaces glossy, glassy, or overly decorative.

### 6.15 Tooltips

- Compact dark inverse surface.
- White text.
- Small radius.
- Minimal delay and motion.

### 6.16 Dividers

Use subtle hairlines rather than thick separators.

Recommended:

```css
border-color: #EDEDED;
```

---

## 7. Layout Principles

### 7.1 Content-first composition

Layout should give visual priority to meaningful content: images, video, titles, avatars, text, reactions, and metadata.

Chrome should remain structurally useful but visually secondary.

### 7.2 Whitespace

Whitespace is moderate rather than luxurious.

The system should avoid both extremes:

- Not cramped like legacy enterprise software.
- Not oversized like a cinematic marketing page.

### 7.3 Grid rhythm

Use predictable spacing increments from the 4px scale.

Grid systems should adapt to content rather than force identical block heights when media or text naturally varies.

### 7.4 Vertical rhythm

A typical content rhythm is:

1. Primary visual/content.
2. Title or primary text.
3. Metadata/social identity.
4. Actions or secondary signals.

### 7.5 Alignment

- Text content is primarily left-aligned.
- Numeric or metadata alignment should optimize scanning.
- Avoid center-aligning large amounts of interface text.
- Use centered alignment for empty/simple states or highly focused moments only.

### 7.6 Surface hierarchy

Prefer this hierarchy:

```text
white canvas
  -> soft gray grouped area
    -> white card/control
      -> subtle border/elevation only where needed
```

Do not create unnecessary nested cards within cards.

---

## 8. Depth & Elevation

The visual system is mostly flat.

### Shadow scale

```text
shadow-sm: 0 1px 2px rgba(0,0,0,0.04)
shadow-md: 0 6px 20px rgba(0,0,0,0.08)
shadow-lg: 0 12px 36px rgba(0,0,0,0.12)
```

### Usage

- Cards: none or `shadow-sm`.
- Floating menus: `shadow-md`.
- Dialogs: `shadow-lg`.
- Sticky/floating controls: subtle elevation only when spatial separation is needed.

### Avoid

- Colored glow.
- Deep multi-layer shadows.
- Glassmorphism as a primary surface language.
- Embossed or neumorphic effects.

---

## 9. Imagery & Media

Photography and video are central to the visual language.

### Image treatment

- High-quality imagery should retain natural saturation.
- UI backgrounds should not compete with images.
- Cropping should feel intentional and content-aware.
- Media corners are softly rounded.
- Avoid decorative frames unless functionally required.

### Cover composition

Portrait-oriented media is common and should be treated naturally. Do not force every asset into square or landscape proportions.

### Overlays

When controls appear on media:

- Use a subtle dark gradient or translucent dark surface only where necessary for legibility.
- Keep overlay icons simple.
- Avoid full-card opaque overlays.

### Avatars and identity

Human identity elements should remain legible and visually close to names, social metadata, and content attribution.

---

## 10. Iconography

Icons should be simple, rounded, and familiar.

Recommended character:

- 1.5–2px stroke.
- Rounded line caps and joins.
- Minimal internal detail.
- Neutral gray by default.
- Filled or red variant for selected/social-active states.

Do not mix several unrelated icon families.

---

## 11. Interaction States

Every interactive component should define:

- Default
- Hover
- Pressed
- Selected
- Focus
- Disabled

### Hover

Hover should generally alter background or text contrast slightly, not create dramatic movement.

### Selected

Selected state may use:

- Brand red text/icon.
- Soft red surface.
- Thin red indicator.
- Filled icon for social interactions.

### Focus

Keyboard focus must be visible. Use a clear border or soft focus ring.

### Disabled

Disabled controls should reduce contrast without disappearing completely.

---

## 12. Motion

Motion is functional and subtle.

Recommended timing:

| Interaction | Duration |
|---|---:|
| Hover feedback | 100–150ms |
| Small popover | 120–180ms |
| Dialog | 160–220ms |
| Drawer/panel | 180–240ms |

Preferred easing:

- `ease-out`
- standard UI cubic-bezier curves

Avoid:

- Large bouncing animations.
- Aggressive spring overshoot.
- Long cinematic page transitions.
- Constant pulsing brand-red effects.
- Decorative motion that competes with content.

---

## 13. States & Feedback

### Success

Use green for confirmed success, not brand red.

### Warning

Use warm amber/orange.

### Error

Use semantic red distinct enough in context from normal brand emphasis, accompanied by text or icon.

### Information

Use neutral or blue information styling.

### Loading

- Skeleton surfaces use neutral gray.
- Spinners stay compact.
- Avoid brand-red loading treatments everywhere.

### Empty states

- Keep illustration/icon lightweight.
- Use short explanatory text.
- Avoid oversized decorative artwork unless the surrounding experience is intentionally playful.

---

## 14. Do's and Don'ts

### Do

- Keep the interface bright and neutral.
- Let images and video carry most color.
- Use red as a deliberate brand signal.
- Use soft rounded corners consistently.
- Maintain clear dark-text hierarchy.
- Use moderate whitespace.
- Keep shadows subtle.
- Make avatars and social identity easy to recognize.
- Use lightweight hover and selected states.
- Keep controls simple and contemporary.

### Don't

- Do not turn the entire UI red.
- Do not treat red as the only semantic color.
- Do not use black/dark mode as the default brand expression.
- Do not add purple AI gradients, neon glow, or cyber aesthetics.
- Do not use excessive glassmorphism.
- Do not over-round every container into large pills.
- Do not use oversized marketing typography throughout an interface.
- Do not bury content under heavy card chrome.
- Do not stack shadows, borders, and tinted backgrounds unnecessarily.
- Do not introduce decorative gradients without strong visual justification.

---

## 15. Responsive Behavior

The design language should survive across form factors without changing its identity.

### Large screens

- Allow more whitespace around major groups.
- Maintain moderate content density.
- Media can expand, but avoid unnecessarily stretching text lines.

### Medium screens

- Reduce horizontal gaps before reducing text size.
- Collapse secondary navigation or auxiliary controls.
- Preserve media prominence.

### Small screens

- Use single-column content flow where appropriate.
- Maintain comfortable touch targets.
- Allow controls to wrap or collapse.
- Keep primary actions reachable.
- Preserve typography hierarchy with smaller spacing rather than extreme font reduction.

### Touch targets

Interactive areas should generally be at least 36–44px in one dimension depending on density and context.

---

## 16. Accessibility Guardrails

- Maintain readable contrast for all essential text.
- Do not communicate state through color alone.
- Keep focus states visible.
- Give icon-only controls accessible labels.
- Maintain readable text at smaller sizes.
- Preserve touch/click target size.
- Provide text labels or tooltips when icon meaning is ambiguous.

Accessibility takes priority over visual imitation.

---

## 17. Agent Prompt Guide

### Core instruction

```text
Read DESIGN.md before implementing or modifying the interface.

Use the Xiaohongshu visual language defined here as the design source of truth.
Apply its color roles, typography, spacing, corner radius, component styling, content-first hierarchy, image treatment, elevation, interaction states, and motion principles.

Do not copy any specific Xiaohongshu page layout unless explicitly requested.
Do not invent product structure from this document.
Do not overuse the red brand color.
Do not introduce unrelated SaaS, cyber, glassmorphism, or generic AI visual language.

The result should feel recognizably Xiaohongshu-inspired through visual grammar, not through literal page imitation.
```

### When creating an undefined component

```text
For any component not explicitly defined in DESIGN.md:
1. derive its colors from the existing color roles;
2. use the nearest existing radius token;
3. use the 4px spacing scale;
4. keep elevation minimal;
5. preserve content-first hierarchy;
6. use brand red only for meaningful emphasis;
7. prefer neutral modern geometry over decoration.
```

### Visual review checklist

```text
Before finishing, verify:
- Is the canvas primarily white or neutral?
- Is red used selectively rather than decoratively?
- Does content remain more visually prominent than UI chrome?
- Are typography and spacing compact but comfortable?
- Are rounded corners soft but restrained?
- Are shadows minimal?
- Are images, avatars, and social identity treated as first-class visual elements?
- Are interaction states clear?
- Are semantic colors distinct from brand color?
- Does the interface avoid unrelated visual trends?
```

---

## 18. Summary Signature

The Xiaohongshu visual signature can be reduced to this formula:

```text
bright white canvas
+ vivid but restrained red brand accent
+ near-black direct typography
+ soft neutral gray structure
+ rounded but controlled geometry
+ minimal elevation
+ strong imagery and human identity
+ lightweight social interaction states
= Xiaohongshu visual language
```

Use this DESIGN.md as a visual language reference, not as a page template or product architecture specification.

---

## 19. Project Confirmation Lock — xhs-xuanpin V1

The V1 visual and interaction direction for this project has been explicitly confirmed.

Before implementing or modifying UI, also read:

- `design/visual-contract.md` — confirmed project-level visual and interaction constraints.
- `design/mockup.html` — confirmed core-page design mockup.
- `design/screenshots/` — static reference renders.

For this project, `design/visual-contract.md` takes precedence when it narrows or overrides the general guidance in this document.

Do not independently replace the confirmed style, layout skeleton, typography floor, gray-text contrast, phone-panel behavior, or export interaction. Any change to confirmed parts must be shown for review first and written back into the design contract only after user confirmation.
