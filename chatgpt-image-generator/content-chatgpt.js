// Runs on https://chatgpt.com/* — world: MAIN
// Dormant until background sends {action:"injectPrompt"}

let activeJobId = null;
let observer    = null;
let pollTimer   = null;
let timeoutTimer = null;

function cleanup() {
  if (observer)    { observer.disconnect(); observer = null; }
  if (pollTimer)   { clearInterval(pollTimer); pollTimer = null; }
  if (timeoutTimer){ clearTimeout(timeoutTimer); timeoutTimer = null; }
  activeJobId = null;
}

function sendError(reason) {
  const jobId = activeJobId;
  cleanup();
  chrome.runtime.sendMessage({ action: 'chatgptError', reason, jobId });
}

function sendStatus(message) {
  chrome.runtime.sendMessage({ action: 'chatgptStatus', message, jobId: activeJobId });
}

// ── Image detection ───────────────────────────────────────────────────────────

function isGeneratedImage(img) {
  const src = img.src || '';
  if (!src.includes('oaiusercontent.com') && !src.includes('openai.com/files')) return false;
  if (!img.closest('[data-message-author-role="assistant"]')) return false;
  return img.complete && img.naturalWidth > 50;
}

function checkForImage() {
  const imgs = document.querySelectorAll('[data-message-author-role="assistant"] img');
  for (const img of imgs) {
    if (isGeneratedImage(img)) {
      const jobId = activeJobId;
      const imageUrl = img.src;
      cleanup();
      chrome.runtime.sendMessage({ action: 'imageReady', imageUrl, jobId });
      return true;
    }
  }
  return false;
}

function startWatchingForImage() {
  sendStatus('Prompt sent — waiting for image…');

  // 90-second hard timeout
  timeoutTimer = setTimeout(() => sendError('timeout'), 90_000);

  // Defensive poll every 4 seconds
  pollTimer = setInterval(() => checkForImage(), 4_000);

  // MutationObserver for real-time detection
  observer = new MutationObserver(() => checkForImage());
  observer.observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ['src'] });
}

// ── Prompt injection ──────────────────────────────────────────────────────────

async function waitFor(selector, timeout = 8000) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    const el = document.querySelector(selector);
    if (el) return el;
    await new Promise(r => setTimeout(r, 200));
  }
  return null;
}

async function injectAndSend(prompt) {
  sendStatus('Opening ChatGPT…');

  // Check login
  const loginLink = document.querySelector('a[href*="/auth/login"]');
  const sidebar   = document.querySelector('nav[aria-label], [data-testid="profile-button"]');
  if (loginLink && !sidebar) {
    sendError('not_logged_in');
    return;
  }

  // If on an existing conversation, navigate to fresh chat
  if (window.location.pathname.startsWith('/c/')) {
    sendStatus('Starting fresh chat…');
    const newChatBtn = document.querySelector(
      'a[href="/"], [data-testid="create-new-chat-button"], [aria-label="New chat"]'
    );
    if (newChatBtn) {
      newChatBtn.click();
      await new Promise(r => setTimeout(r, 2000));
    } else {
      window.location.href = 'https://chatgpt.com/';
      return; // page reloads; content script reinjects; background will re-send injectPrompt
    }
  }

  // Wait for the input
  sendStatus('Waiting for ChatGPT input…');
  const textarea = await waitFor('#prompt-textarea, [contenteditable][id*="prompt"]', 8000);
  if (!textarea) {
    sendError('dom_error');
    return;
  }

  // Inject text using clipboard paste simulation (most reliable for ProseMirror)
  textarea.focus();
  try {
    const dt = new DataTransfer();
    dt.setData('text/plain', prompt);
    textarea.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true }));
  } catch (_) {
    // Fallback: execCommand
    document.execCommand('selectAll', false, null);
    document.execCommand('insertText', false, prompt);
  }

  // Wait for React to register the input
  await new Promise(r => setTimeout(r, 500));

  // Find the send button (try multiple selectors)
  let sendBtn = null;
  const sendSelectors = [
    'button[data-testid="send-button"]',
    'button[aria-label*="Send"]',
    'button[aria-label*="send"]',
    'form button[type="submit"]',
  ];

  // Wait up to 2s for the button to become enabled
  const btnStart = Date.now();
  while (Date.now() - btnStart < 2500) {
    for (const sel of sendSelectors) {
      const btn = document.querySelector(sel);
      if (btn && !btn.disabled) { sendBtn = btn; break; }
    }
    if (sendBtn) break;
    await new Promise(r => setTimeout(r, 200));
  }

  if (!sendBtn) {
    // Last resort: try any button with an SVG that looks like a send arrow
    sendBtn = document.querySelector('button:not([disabled])[data-testid*="send"]');
  }

  if (!sendBtn) {
    sendError('dom_error');
    return;
  }

  sendBtn.click();
  startWatchingForImage();
}

// ── Message listener ──────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.action !== 'injectPrompt') return;

  // Abort any previous job
  if (activeJobId) cleanup();

  activeJobId = msg.jobId;
  injectAndSend(msg.prompt).catch(err => {
    console.error('[cgpt-ext]', err);
    sendError('dom_error');
  });
});
