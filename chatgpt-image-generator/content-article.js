// Runs on http://localhost:5001/* — world: MAIN
// Injects "🤖 ChatGPT" buttons that show the image prompt in a modal on click.

// ── Modal ─────────────────────────────────────────────────────────────────────

function showPromptModal(promptText) {
  // Remove existing modal if any
  document.getElementById('cgpt-modal')?.remove();

  const overlay = document.createElement('div');
  overlay.id = 'cgpt-modal';
  overlay.style.cssText = [
    'position:fixed', 'inset:0', 'z-index:99999',
    'background:rgba(0,0,0,.55)', 'display:flex',
    'align-items:center', 'justify-content:center', 'padding:24px',
  ].join(';');

  overlay.innerHTML = `
    <div style="
      background:#fff;border-radius:12px;padding:22px 24px;
      max-width:640px;width:100%;box-shadow:0 20px 60px rgba(0,0,0,.3);
      font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
      position:relative;
    ">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px">
        <div style="font-weight:700;font-size:13px;color:#7c3aed">🤖 Image Prompt for ChatGPT / DALL·E</div>
        <button id="cgpt-modal-close" style="
          background:none;border:none;cursor:pointer;font-size:20px;
          color:#a8a29e;line-height:1;padding:0 2px
        ">×</button>
      </div>

      <div id="cgpt-prompt-text" style="
        background:#faf5ff;border:1px solid #d8b4fe;border-radius:8px;
        padding:12px 14px;font-size:12px;line-height:1.65;color:#1c1917;
        font-family:'JetBrains Mono','Courier New',monospace;
        white-space:pre-wrap;word-break:break-word;
        max-height:240px;overflow-y:auto;
        user-select:all;
      ">${escHtml(promptText)}</div>

      <div style="display:flex;gap:8px;margin-top:14px">
        <button id="cgpt-copy-btn" style="
          background:#7c3aed;color:#fff;border:none;border-radius:7px;
          padding:8px 16px;font-size:12px;font-weight:600;cursor:pointer;
          flex:1;transition:background .15s
        ">📋 Copy Prompt</button>
        <a href="https://chatgpt.com/" target="_blank" style="
          display:flex;align-items:center;justify-content:center;
          background:#10a37f;color:#fff;border-radius:7px;
          padding:8px 16px;font-size:12px;font-weight:600;
          text-decoration:none;flex:1;text-align:center
        ">↗ Open ChatGPT</a>
      </div>
      <div id="cgpt-copy-msg" style="
        font-size:11px;color:#16a34a;text-align:center;
        margin-top:8px;min-height:16px
      "></div>
    </div>
  `;

  document.body.appendChild(overlay);

  // Close on overlay click or × button
  overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
  document.getElementById('cgpt-modal-close').addEventListener('click', () => overlay.remove());

  // Copy button
  document.getElementById('cgpt-copy-btn').addEventListener('click', () => {
    navigator.clipboard.writeText(promptText).then(() => {
      document.getElementById('cgpt-copy-msg').textContent = '✅ Copied to clipboard!';
      document.getElementById('cgpt-copy-btn').textContent = '✓ Copied';
      setTimeout(() => {
        const msg = document.getElementById('cgpt-copy-msg');
        const btn = document.getElementById('cgpt-copy-btn');
        if (msg) msg.textContent = '';
        if (btn) btn.textContent = '📋 Copy Prompt';
      }, 2000);
    }).catch(() => {
      // Fallback: select the text
      const el = document.getElementById('cgpt-prompt-text');
      const range = document.createRange();
      range.selectNodeContents(el);
      window.getSelection().removeAllRanges();
      window.getSelection().addRange(range);
      document.getElementById('cgpt-copy-msg').textContent = 'Text selected — press Ctrl+C to copy';
    });
  });

  // Close on Escape
  const onKey = e => { if (e.key === 'Escape') { overlay.remove(); document.removeEventListener('keydown', onKey); } };
  document.addEventListener('keydown', onKey);
}

function escHtml(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Button factory ────────────────────────────────────────────────────────────

const BTN_STYLE = 'border-color:#d8b4fe;color:#7c3aed';

function makeCoverButton() {
  const btn = document.createElement('button');
  btn.id = 'cgpt-cover-btn';
  btn.className = 'tb-btn tb-btn-sm';
  btn.style.cssText = BTN_STYLE;
  btn.textContent = '🤖 ChatGPT';
  btn.addEventListener('click', () => {
    const prompt = (document.getElementById('coverPromptText')?.textContent || '').trim();
    if (!prompt) { toast?.('No cover prompt — generate the article first.', 'error'); return; }
    showPromptModal(prompt);
  });
  return btn;
}

function makeSectionButton(idx) {
  const btn = document.createElement('button');
  btn.className = 'tb-btn tb-btn-sm cgpt-sec-btn';
  btn.dataset.idx = idx;
  btn.style.cssText = BTN_STYLE;
  btn.textContent = '🤖 ChatGPT';
  btn.addEventListener('click', () => {
    const prompt = (document.getElementById('imgPrTxt-' + idx)?.textContent || '').trim();
    if (!prompt) { toast?.('No image prompt for this section.', 'error'); return; }
    showPromptModal(prompt);
  });
  return btn;
}

// ── Button injection via MutationObserver ─────────────────────────────────────

function injectCoverButton() {
  const card = document.getElementById('coverImageCard');
  if (!card || card.dataset.cgptInjected) return;
  const btnGroup = card.querySelector('.cover-head div[style*="flex"]') ||
                   card.querySelector('.cover-head > div:last-child');
  if (!btnGroup) return;
  card.dataset.cgptInjected = '1';
  btnGroup.appendChild(makeCoverButton());
}

function injectSectionButtons() {
  document.querySelectorAll('div[id^="imgPr-"]').forEach(box => {
    if (box.dataset.cgptInjected) return;
    const idx = Number(box.id.replace('imgPr-', ''));
    if (isNaN(idx)) return;
    const btnRow = box.querySelector('div[style*="flex"]');
    if (!btnRow) return;
    box.dataset.cgptInjected = '1';
    btnRow.appendChild(makeSectionButton(idx));
  });
}

function injectAll() {
  injectCoverButton();
  injectSectionButtons();
}

const domObserver = new MutationObserver(injectAll);
domObserver.observe(document.body, { subtree: true, childList: true });
injectAll();
