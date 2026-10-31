// tool-theme:start (generated from spritecore/tool_theme.py by sync_tool_theme.py; do not edit)
(() => {
  const root = document.documentElement;
  const button = document.getElementById('theme-toggle');
  const key = 'sprite-tools-theme';
  const effective = () => root.dataset.theme || (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark');
  const label = () => { if (button) button.setAttribute('aria-label', `Switch to ${effective() === 'dark' ? 'light' : 'dark'} theme`); };
  try { const saved = localStorage.getItem(key); if (saved === 'light' || saved === 'dark') root.dataset.theme = saved; } catch (_error) {}
  label();
  if (button) button.addEventListener('click', () => {
    root.dataset.theme = effective() === 'dark' ? 'light' : 'dark';
    try { localStorage.setItem(key, root.dataset.theme); } catch (_error) {}
    label();
  });
})();
// tool-theme:end
