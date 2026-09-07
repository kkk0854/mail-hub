// MAIL HUB 浏览器扩展 - Popup 逻辑
let config = null;
let currentTask = null;
let pollTimer = null;

// 初始化
document.addEventListener('DOMContentLoaded', async () => {
  await loadConfig();
  if (!config || !config.serverUrl || !config.apiKey) {
    document.getElementById('configRequired').style.display = 'block';
    document.getElementById('mainApp').style.display = 'none';
    return;
  }
  document.getElementById('configRequired').style.display = 'none';
  document.getElementById('mainApp').style.display = 'block';
  await testConnection();
  await loadHistory();
});

async function loadConfig() {
  const result = await chrome.storage.sync.get(['serverUrl', 'apiKey', 'defaultPoolId']);
  config = result;
}

function openOptions() {
  chrome.runtime.openOptionsPage();
}

async function testConnection() {
  try {
    const resp = await fetch(`${config.serverUrl}/api/v1/system/version`, {
      headers: { 'X-API-Key': config.apiKey }
    });
    if (resp.ok) {
      const data = await resp.json();
      document.getElementById('connStatus').textContent = `已连接 v${data.current}`;
      document.getElementById('connStatus').style.color = '#b7eb8f';
    } else {
      document.getElementById('connStatus').textContent = '连接失败';
      document.getElementById('connStatus').style.color = '#ffccc7';
    }
  } catch (e) {
    document.getElementById('connStatus').textContent = '连接失败';
    document.getElementById('connStatus').style.color = '#ffccc7';
  }
}

async function claimMailbox() {
  const btn = document.getElementById('claimBtn');
  btn.disabled = true;
  btn.textContent = '申领中...';

  const projectKey = document.getElementById('projectKey').value.trim();
  const matchSender = document.getElementById('matchSender').value.trim();
  const matchSubject = document.getElementById('matchSubject').value.trim();

  try {
    const body = {
      pool_id: config.defaultPoolId || null,
      target_ref: `ext-${Date.now()}`,
      match: {
        sender: matchSender || '*',
        subject_contains: matchSubject || ''
      },
      timeout_seconds: 300,
      project_key: projectKey || null,
      caller_id: 'browser-extension'
    };

    const resp = await fetch(`${config.serverUrl}/api/v1/registration-tasks`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': config.apiKey
      },
      body: JSON.stringify(body)
    });

    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.detail || `HTTP ${resp.status}`);
    }

    currentTask = await resp.json();
    renderWaiting(currentTask);
    startPolling(currentTask.id);
    saveToHistory(currentTask);

  } catch (e) {
    showError(`申领失败: ${e.message}`);
    btn.disabled = false;
    btn.textContent = '🚀 一键申领邮箱';
  }
}

function renderWaiting(task) {
  const area = document.getElementById('resultArea');
  area.innerHTML = `
    <div class="result-card">
      <div class="email">📧 ${task.mailbox || '分配中...'}</div>
      <div class="meta">任务ID: ${task.id} | 状态: ${task.state}</div>
      <div class="waiting">
        <div class="spinner"></div>
        <div>等待验证邮件...</div>
        <div style="font-size:10px;margin-top:4px;">超时时间: ${new Date(task.expires_at).toLocaleTimeString()}</div>
      </div>
      <div class="actions">
        <button class="btn btn-secondary btn-sm" onclick="copyEmail('${task.mailbox}')">复制邮箱</button>
        <button class="btn btn-danger btn-sm" onclick="cancelTask('${task.id}')">取消任务</button>
      </div>
    </div>
  `;
}

function renderResult(task, result) {
  const area = document.getElementById('resultArea');
  const isOTP = result.type === 'OTP';
  area.innerHTML = `
    <div class="result-card">
      <div class="email">📧 ${task.mailbox || ''}</div>
      <div class="meta">状态: 结果就绪 | 类型: ${result.type}</div>
      ${isOTP ? `<div class="code">${result.value}</div>` : `<div style="word-break:break-all;background:#f5f5ff;padding:8px;border-radius:6px;margin:8px 0;font-size:12px;">${result.value}</div>`}
      <div class="actions">
        <button class="btn btn-primary btn-sm" onclick="copyText('${result.value.replace(/'/g, "\\'")}')">复制结果</button>
        <button class="btn btn-success btn-sm" onclick="completeTask('${task.id}', 'success')">✅ 完成并释放</button>
      </div>
    </div>
  `;

  // 桌面通知
  chrome.notifications.create({
    type: 'basic',
    iconUrl: 'icons/icon128.png',
    title: 'MAIL HUB: 验证码已提取',
    message: `${result.type}: ${result.value}`,
    priority: 2
  });
}

function startPolling(taskId) {
  if (pollTimer) clearInterval(pollTimer);
  let pollCount = 0;
  pollTimer = setInterval(async () => {
    pollCount++;
    try {
      const resp = await fetch(`${config.serverUrl}/api/v1/registration-tasks/${taskId}/result`, {
        headers: { 'X-API-Key': config.apiKey }
      });
      if (!resp.ok) return;
      const data = await resp.json();
      if (data.result && data.status === 'RESULT_READY' || data.status === 'COMPLETED' || data.status === 'WAITING_CALLBACK') {
        clearInterval(pollTimer);
        pollTimer = null;
        // 获取完整任务信息
        const taskResp = await fetch(`${config.serverUrl}/api/v1/registration-tasks/${taskId}`, {
          headers: { 'X-API-Key': config.apiKey }
        });
        const task = await taskResp.json();
        renderResult(task, data.result);
        document.getElementById('claimBtn').disabled = false;
        document.getElementById('claimBtn').textContent = '🚀 一键申领邮箱';
      } else if (data.status === 'TIMEOUT' || data.status === 'CANCELLED' || data.status === 'MAILBOX_ERROR') {
        clearInterval(pollTimer);
        pollTimer = null;
        showError(`任务结束: ${data.status}`);
        document.getElementById('claimBtn').disabled = false;
        document.getElementById('claimBtn').textContent = '🚀 一键申领邮箱';
      }
    } catch (e) {
      console.error('Poll error:', e);
    }
    if (pollCount > 120) { // 10分钟超时保护
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }, 2000);
}

async function completeTask(taskId, result) {
  try {
    await fetch(`${config.serverUrl}/api/v1/registration-tasks/${taskId}/claim-complete`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': config.apiKey
      },
      body: JSON.stringify({ result, note: 'browser extension' })
    });
    document.getElementById('resultArea').innerHTML = `
      <div class="result-card" style="text-align:center;padding:20px;">
        <div style="font-size:32px;">✅</div>
        <div style="font-weight:600;margin-top:8px;">任务已完成，邮箱已释放</div>
      </div>
    `;
    await loadHistory();
  } catch (e) {
    showError(`完成失败: ${e.message}`);
  }
}

async function cancelTask(taskId) {
  if (!confirm('确定取消这个任务吗？')) return;
  try {
    await fetch(`${config.serverUrl}/api/v1/registration-tasks/${taskId}/cancel`, {
      method: 'POST',
      headers: { 'X-API-Key': config.apiKey }
    });
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    document.getElementById('resultArea').innerHTML = '';
    document.getElementById('claimBtn').disabled = false;
    document.getElementById('claimBtn').textContent = '🚀 一键申领邮箱';
    await loadHistory();
  } catch (e) {
    showError(`取消失败: ${e.message}`);
  }
}

function copyEmail(email) {
  if (email) copyText(email);
}

function copyText(text) {
  navigator.clipboard.writeText(text).then(() => {
    chrome.notifications.create({
      type: 'basic',
      iconUrl: 'icons/icon128.png',
      title: '已复制',
      message: text.length > 50 ? text.substring(0, 50) + '...' : text,
      priority: 1
    });
  });
}

function showError(msg) {
  const area = document.getElementById('resultArea');
  area.innerHTML = `<div class="error">${msg}</div>` + area.innerHTML;
}

async function saveToHistory(task) {
  const history = await chrome.storage.local.get(['taskHistory']);
  const list = history.taskHistory || [];
  list.unshift({ id: task.id, mailbox: task.mailbox, state: task.state, createdAt: Date.now() });
  if (list.length > 10) list.pop();
  await chrome.storage.local.set({ taskHistory: list });
  await loadHistory();
}

async function loadHistory() {
  const history = await chrome.storage.local.get(['taskHistory']);
  const list = history.taskHistory || [];
  if (list.length === 0) return;
  document.getElementById('historySection').style.display = 'block';
  document.getElementById('historyList').innerHTML = list.map(t => `
    <div class="history-item">
      <span class="email">${t.mailbox || '无邮箱'}</span>
      <span class="state">${t.state}</span>
    </div>
  `).join('');
}
