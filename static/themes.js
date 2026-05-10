/**
 * PDF Clean — Minimal Theme Switcher (Dark & Light only)
 */
(function () {
  const THEMES = [
    { id: 'dark',  label: 'Dark Mode',  emoji: '🌙' },
    { id: 'light', label: 'Light Mode', emoji: '☀️' }
  ];

  function applyTheme(id) {
    document.documentElement.setAttribute('data-theme', id);
    localStorage.setItem('pdfclean-theme', id);
    
    // Update active state in panel
    document.querySelectorAll('.ts-item').forEach(el => {
      el.classList.toggle('active', el.dataset.theme === id);
    });
    
    // Update toggle icon
    const toggle = document.getElementById('ts-toggle');
    if (toggle) {
      toggle.innerHTML = id === 'dark' ? '🌙' : '☀️';
    }

    // Propagate to same-origin iframes
    document.querySelectorAll('iframe').forEach(frame => {
      try {
        frame.contentDocument.documentElement.setAttribute('data-theme', id);
      } catch (_) {}
    });
  }

  function buildWidget() {
    const root = document.getElementById('theme-switcher');
    if (!root) return;

    const saved = localStorage.getItem('pdfclean-theme') || 'dark';
    applyTheme(saved);

    const itemsHTML = THEMES.map(t => `
      <div class="ts-item ${t.id === saved ? 'active' : ''}" data-theme="${t.id}">
        <span>${t.emoji} ${t.label}</span>
      </div>
    `).join('');

    root.innerHTML = `
      <div class="ts-panel" id="ts-panel">
        <div class="ts-items">${itemsHTML}</div>
      </div>
      <button class="ts-toggle" id="ts-toggle" title="Change theme">${saved === 'dark' ? '🌙' : '☀️'}</button>
    `;

    const btn = document.getElementById('ts-toggle');
    const panel = document.getElementById('ts-panel');
    
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      panel.classList.toggle('open');
    });

    document.addEventListener('click', () => panel.classList.remove('open'));
    panel.addEventListener('click', e => e.stopPropagation());

    root.querySelectorAll('.ts-item').forEach(el => {
      el.addEventListener('click', () => {
        applyTheme(el.dataset.theme);
        panel.classList.remove('open');
      });
    });
  }

  if (window === window.top) {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', buildWidget);
    } else {
      buildWidget();
    }
  }

  const saved = localStorage.getItem('pdfclean-theme') || 'dark';
  document.documentElement.setAttribute('data-theme', saved);
})();
