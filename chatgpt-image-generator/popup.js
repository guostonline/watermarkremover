const promptInput = document.getElementById('promptInput');
const genBtn      = document.getElementById('genBtn');
const statusEl    = document.getElementById('status');
const statusText  = document.getElementById('statusText');
const resultEl    = document.getElementById('result');
const errorBox    = document.getElementById('errorBox');

// Restore last prompt
chrome.storage.local.get('lastPrompt', ({ lastPrompt }) => {
  if (lastPrompt) promptInput.value = lastPrompt;
});

function setStatus(msg) {
  statusEl.className = 'visible';
  statusText.textContent = msg;
  resultEl.className = '';
  errorBox.className = '';
}

function setResult(msg) {
  resultEl.textContent = msg;
  resultEl.className = 'visible';
  statusEl.className = '';
  errorBox.className = '';
  genBtn.disabled = false;
  genBtn.textContent = '🤖 Generate Image';
}

function setError(msg) {
  errorBox.textContent = '⚠ ' + msg;
  errorBox.className = 'visible';
  statusEl.className = '';
  genBtn.disabled = false;
  genBtn.textContent = '🤖 Generate Image';
}

genBtn.addEventListener('click', () => {
  const prompt = promptInput.value.trim();
  if (!prompt) { setError('Please enter a prompt.'); return; }

  chrome.storage.local.set({ lastPrompt: prompt });
  genBtn.disabled = true;
  genBtn.textContent = '⏳ Working…';
  setStatus('Opening ChatGPT…');
  resultEl.className = '';
  errorBox.className = '';

  chrome.runtime.sendMessage({ action: 'generateImageManual', prompt });
});

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type !== 'manual') return;
  if (msg.action === 'statusUpdate') setStatus(msg.message);
  if (msg.action === 'imageError') {
    const reasons = {
      not_logged_in: 'Please log in to ChatGPT first — the tab is open for you.',
      timeout: 'Timed out waiting for image. ChatGPT may be slow — try again.',
      dom_error: 'Could not find ChatGPT input. Refresh the ChatGPT tab and retry.',
    };
    setError(reasons[msg.reason] || msg.reason);
  }
  if (msg.action === 'imageDone') {
    setResult('✅ Image saved to your Downloads folder.');
  }
});
