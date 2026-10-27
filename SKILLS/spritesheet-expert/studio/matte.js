// Paints the shared review mattes (tool-theme.css tokens) onto a canvas.
export function paintMatte(context, width, height, kind) {
  const css = getComputedStyle(document.documentElement);
  const token = name => css.getPropertyValue(name).trim();
  if (kind !== "checker") {
    context.fillStyle = token(`--matte-${kind}`) || token("--matte-gray");
    context.fillRect(0, 0, width, height);
    return;
  }
  const size = parseInt(token("--checker-size"), 10) || 16;
  context.fillStyle = token("--checker-a");
  context.fillRect(0, 0, width, height);
  context.fillStyle = token("--checker-b");
  for (let y = 0; y < height; y += size)
    for (let x = (y / size) % 2 ? 0 : size; x < width; x += size * 2) context.fillRect(x, y, size, size);
}
