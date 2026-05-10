// ── Helpers ──────────────────────────────────────────────────────────────────

async function getJobs() {
  const { jobs } = await chrome.storage.session.get('jobs');
  return jobs || {};
}

async function saveJob(job) {
  const jobs = await getJobs();
  jobs[job.jobId] = job;
  await chrome.storage.session.set({ jobs });
}

async function removeJob(jobId) {
  const jobs = await getJobs();
  delete jobs[jobId];
  await chrome.storage.session.set({ jobs });
}

async function getJobByTab(chatgptTabId) {
  const jobs = await getJobs();
  return Object.values(jobs).find(j => j.chatgptTabId === chatgptTabId) || null;
}

async function sendToArticleTab(tabId, msg) {
  if (!tabId) return;
  try {
    await chrome.tabs.sendMessage(tabId, msg);
  } catch (_) {
    // Article tab may have been closed
  }
}

// Send to all extension views (popup)
function broadcastToViews(msg) {
  chrome.runtime.sendMessage(msg).catch(() => {});
}

// ── Tab management ────────────────────────────────────────────────────────────

async function openOrReuseChatGPTTab(job) {
  const { cgptTabId } = await chrome.storage.local.get('cgptTabId');
  let tab = null;

  if (cgptTabId) {
    try { tab = await chrome.tabs.get(cgptTabId); } catch (_) { tab = null; }
  }

  if (!tab) {
    tab = await chrome.tabs.create({ url: 'https://chatgpt.com/', active: true });
  } else {
    // Navigate to fresh chat if on an existing conversation or wrong domain
    const url = tab.url || '';
    if (!url.includes('chatgpt.com') || url.includes('/c/')) {
      await chrome.tabs.update(tab.id, { url: 'https://chatgpt.com/', active: true });
    } else {
      await chrome.tabs.update(tab.id, { active: true });
    }
  }

  job.chatgptTabId = tab.id;
  await chrome.storage.local.set({ cgptTabId: tab.id });
  await saveJob(job);
}

// ── Send prompt with retry (content script may not be ready yet) ─────────────

async function sendInjectPrompt(tabId, job, attempt = 0) {
  try {
    await chrome.tabs.sendMessage(tabId, {
      action: 'injectPrompt',
      prompt: job.prompt,
      jobId:  job.jobId,
    });
    job.status = 'injecting';
    await saveJob(job);
  } catch (_) {
    if (attempt < 6) {
      setTimeout(() => sendInjectPrompt(tabId, job, attempt + 1), 600);
    } else {
      await handleError(job.jobId, 'dom_error');
    }
  }
}

// ── Error / cleanup ───────────────────────────────────────────────────────────

async function handleError(jobId, reason) {
  const jobs = await getJobs();
  const job = jobs[jobId];
  if (!job) return;
  job.status = 'error';
  await saveJob(job);

  const errMsg = { action: 'imageError', reason, jobId, type: job.type, sectionIdx: job.sectionIdx };
  if (job.type === 'manual') {
    broadcastToViews({ ...errMsg });
  } else {
    await sendToArticleTab(job.articleTabId, errMsg);
  }
  await chrome.alarms.clear('timeout_' + jobId);
  await removeJob(jobId);
}

// ── Fetch image with retries ──────────────────────────────────────────────────

async function fetchWithRetry(url, attempts = 3, delay = 1000) {
  for (let i = 0; i < attempts; i++) {
    try {
      const res = await fetch(url);
      if (res.ok) {
        const buf = await res.arrayBuffer();
        const mimeType = res.headers.get('content-type') || 'image/png';
        return { buf, mimeType };
      }
    } catch (_) {}
    if (i < attempts - 1) await new Promise(r => setTimeout(r, delay * Math.pow(2, i)));
  }
  return null;
}

function arrayBufferToBase64(buf) {
  const bytes = new Uint8Array(buf);
  let binary = '';
  for (let b of bytes) binary += String.fromCharCode(b);
  return btoa(binary);
}

// ── Tabs onUpdated — inject prompt when ChatGPT finishes loading ──────────────

chrome.tabs.onUpdated.addListener(async (tabId, info, tab) => {
  if (info.status !== 'complete') return;
  const job = await getJobByTab(tabId);
  if (!job || job.status !== 'pending') return;

  const url = tab.url || '';
  if (!url.includes('chatgpt.com')) return;

  // If still on a conversation URL, navigate to fresh chat
  if (url.includes('/c/')) {
    await chrome.tabs.update(tabId, { url: 'https://chatgpt.com/' });
    return;
  }

  await sendInjectPrompt(tabId, job);
});

// ── Message handler ───────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  handleMessage(msg, sender).catch(console.error);
  return false; // async handled inside
});

async function handleMessage(msg, sender) {
  // ── Initiate from article editor or popup ──
  if (msg.action === 'generateImage' || msg.action === 'generateImageManual') {
    const job = {
      jobId:        crypto.randomUUID(),
      prompt:       msg.prompt,
      type:         msg.action === 'generateImageManual' ? 'manual' : msg.type,
      sectionIdx:   msg.sectionIdx ?? null,
      articleTabId: msg.action === 'generateImageManual' ? null : sender.tab?.id ?? null,
      chatgptTabId: null,
      status:       'pending',
    };
    await saveJob(job);

    // Arm 3-minute timeout watchdog
    await chrome.alarms.create('timeout_' + job.jobId, { delayInMinutes: 3 });

    await openOrReuseChatGPTTab(job);

    // If tab was already on chatgpt.com (not /c/), onUpdated won't fire for "complete"
    // so check immediately
    if (job.chatgptTabId) {
      try {
        const tab = await chrome.tabs.get(job.chatgptTabId);
        if (tab.status === 'complete' && tab.url?.includes('chatgpt.com') && !tab.url.includes('/c/')) {
          await sendInjectPrompt(job.chatgptTabId, job);
        }
      } catch (_) {}
    }
    return;
  }

  // ── Status update from ChatGPT content script ──
  if (msg.action === 'chatgptStatus') {
    const jobs = await getJobs();
    const job = jobs[msg.jobId];
    if (!job) return;
    const statusMsg = { action: 'statusUpdate', message: msg.message, jobId: msg.jobId, type: job.type, sectionIdx: job.sectionIdx };
    if (job.type === 'manual') broadcastToViews(statusMsg);
    else await sendToArticleTab(job.articleTabId, statusMsg);
    return;
  }

  // ── Image detected in ChatGPT ──
  if (msg.action === 'imageReady') {
    const jobs = await getJobs();
    const job = jobs[msg.jobId];
    if (!job) return;

    job.status = 'fetching';
    await saveJob(job);

    // Always download to disk as backup
    chrome.downloads.download({
      url: msg.imageUrl,
      filename: 'chatgpt-image-' + msg.jobId.slice(0, 8) + '.png',
      saveAs: false,
    });

    if (job.type === 'manual') {
      broadcastToViews({ action: 'imageDone', type: 'manual' });
      await chrome.alarms.clear('timeout_' + msg.jobId);
      await removeJob(msg.jobId);
      return;
    }

    // Fetch blob and send to article tab
    const result = await fetchWithRetry(msg.imageUrl);
    if (!result) {
      await handleError(msg.jobId, 'fetch_failed');
      return;
    }

    const base64 = arrayBufferToBase64(result.buf);
    await sendToArticleTab(job.articleTabId, {
      action:     'imageData',
      base64,
      mimeType:   result.mimeType,
      jobId:      msg.jobId,
      type:       job.type,
      sectionIdx: job.sectionIdx,
    });

    await chrome.alarms.clear('timeout_' + msg.jobId);
    await removeJob(msg.jobId);
    return;
  }

  // ── Error from ChatGPT content script ──
  if (msg.action === 'chatgptError') {
    await handleError(msg.jobId, msg.reason);
    return;
  }
}

// ── Alarm: timeout watchdog ───────────────────────────────────────────────────

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (!alarm.name.startsWith('timeout_')) return;
  const jobId = alarm.name.replace('timeout_', '');
  const jobs = await getJobs();
  if (jobs[jobId] && jobs[jobId].status !== 'done' && jobs[jobId].status !== 'error') {
    await handleError(jobId, 'timeout');
  }
});
