export const DEFAULT_ACCENT = "#FF4FA3";
export const FONT_STACK = "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif";
export const THEMES = ["Light", "Dark", "Spicy"];
export const SWATCHES = ["#FF4FA3", "#FF3048", "#FF7A30", "#FFC93A", "#7ED957", "#2ED6D6", "#3D8BFF", "#9B6CFF", "#FF66C4"];

export const THEME_TOKENS = {
  Dark: {
    background: "#15161A",
    surface: "#22242A",
    surfaceRaised: "#2D3037",
    surfaceHover: "#373A43",
    text: "#FFFFFF",
    textSecondary: "#CED1D8",
    textMuted: "#8D929C",
    border: "#444852",
    borderStrong: "#5A5F6B",
  },
  Light: {
    background: "#F1F3F6",
    surface: "#FFFFFF",
    surfaceRaised: "#E5E8ED",
    surfaceHover: "#DCE1E7",
    text: "#17191D",
    textSecondary: "#4D525A",
    textMuted: "#777D87",
    border: "#C7CCD4",
    borderStrong: "#AAB1BC",
  },
  Spicy: {
    background: "#0D071F",
    surface: "#231937",
    surfaceRaised: "#2D2145",
    surfaceHover: "#382854",
    text: "#FFFFFF",
    textSecondary: "#D8D0E5",
    textMuted: "#9C90AE",
    border: "rgba(255,255,255,0.12)",
    borderStrong: "rgba(255,255,255,0.20)",
    primaryPurple: "#7B3FF2",
    secondaryTeal: "#00D4B8",
    accentGold: "#FFB800",
  },
};

export function normalizeHex(value) {
  const text = String(value || "").trim();
  const match = text.match(/^#?([0-9a-fA-F]{6})$/);
  return match ? `#${match[1].toUpperCase()}` : null;
}

export function hexToRgba(hex, alpha) {
  const clean = normalizeHex(hex) || DEFAULT_ACCENT;
  const intValue = parseInt(clean.slice(1), 16);
  const r = (intValue >> 16) & 255;
  const g = (intValue >> 8) & 255;
  const b = intValue & 255;
  return `rgba(${r},${g},${b},${alpha})`;
}

export function hexToRgb(hex) {
  const clean = normalizeHex(hex) || DEFAULT_ACCENT;
  const intValue = parseInt(clean.slice(1), 16);
  return {
    r: (intValue >> 16) & 255,
    g: (intValue >> 8) & 255,
    b: intValue & 255,
  };
}

export function relativeLuminance({ r, g, b }) {
  const linear = [r, g, b].map((channel) => {
    const value = channel / 255;
    return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

export function buildAccentPalette(accent, contrastMode) {
  const accentSolid = normalizeHex(accent) || DEFAULT_ACCENT;
  const accentLuma = relativeLuminance(hexToRgb(accentSolid));
  const accentForeground = accentLuma > 0.58 ? "#17191D" : "#FFFFFF";
  return {
    contrastMode,
    accentSolid,
    accentForeground,
    accentBorder: accentSolid,
    accentTint: hexToRgba(accentSolid, 0.2),
    accentTintStrong: hexToRgba(accentSolid, 0.28),
  };
}

export function activeFill(palette, fallbackAlpha = 0.2) {
  return palette.contrastMode ? palette.accentSolid : hexToRgba(palette.accentSolid, fallbackAlpha);
}

export function activeForeground(palette, normalColor) {
  return palette.contrastMode ? palette.accentForeground : normalColor;
}

export function roundedRect(ctx, x, y, w, h, r) {
  const radius = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + radius, y);
  ctx.lineTo(x + w - radius, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + radius);
  ctx.lineTo(x + w, y + h - radius);
  ctx.quadraticCurveTo(x + w, y + h, x + w - radius, y + h);
  ctx.lineTo(x + radius, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - radius);
  ctx.lineTo(x, y + radius);
  ctx.quadraticCurveTo(x, y, x + radius, y);
  ctx.closePath();
}

export function drawRound(ctx, box, fill, stroke, lineWidth = 1, radius = 7) {
  roundedRect(ctx, box.x, box.y, box.w, box.h, radius);
  ctx.fillStyle = fill;
  ctx.fill();
  if (stroke) {
    ctx.lineWidth = lineWidth;
    ctx.strokeStyle = stroke;
    ctx.stroke();
  }
}

export function drawText(ctx, text, x, y, size, color, weight = "500", align = "left") {
  ctx.fillStyle = color;
  ctx.font = `${weight} ${size}px ${FONT_STACK}`;
  ctx.textAlign = align;
  ctx.textBaseline = "middle";
  ctx.fillText(text, x, y);
}

export function ellipsize(ctx, text, maxWidth) {
  const value = String(text ?? "");
  if (ctx.measureText(value).width <= maxWidth) {
    return value;
  }
  if (ctx.measureText("...").width > maxWidth) {
    return "";
  }
  const characters = Array.from(value);
  let low = 0;
  let high = characters.length;
  while (low < high) {
    const middle = Math.ceil((low + high) / 2);
    if (ctx.measureText(`${characters.slice(0, middle).join("")}...`).width <= maxWidth) {
      low = middle;
    } else {
      high = middle - 1;
    }
  }
  return `${characters.slice(0, low).join("")}...`;
}

export function drawPaletteIcon(ctx, x, y, color, tokens) {
  ctx.fillStyle = hexToRgba(color, 0.16);
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.arc(x + 9, y + 9, 9, 0.22 * Math.PI, 1.95 * Math.PI);
  ctx.quadraticCurveTo(x + 17, y + 18, x + 10, y + 18);
  ctx.quadraticCurveTo(x + 2, y + 18, x, y + 10);
  ctx.quadraticCurveTo(x, y + 2, x + 9, y);
  ctx.closePath();
  ctx.fill();
  ctx.stroke();
  for (const dot of [[6, 7], [11, 5], [14, 10]]) {
    ctx.beginPath();
    ctx.arc(x + dot[0], y + dot[1], 1.7, 0, Math.PI * 2);
    ctx.fillStyle = tokens.textSecondary;
    ctx.fill();
  }
}
