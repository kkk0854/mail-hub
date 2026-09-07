// MAIL HUB 浏览器扩展 - 配置页面逻辑
document.addEventListener('DOMContentLoaded', async () => {
  const config = await chrome.storage.sync.get(['serverUrl', 'apiKey', 'defaultPoolId']);
  document.getElementById('serverUrl').value = config.serverUrl || '';
  document.getElementById('apiKey').value = config.apiKey || '';
  document.getElementById('defaultPoolId').value = config.defaultPoolId || '';
});

async function saveConfig() {
  const serverUrl = document.getElementById('serverUrl').value.trim().replace(/\/$/, '');
  const apiKey = document.getElementById('apiKey').value.trim();
  const defaultPoolId = document.getElementById('defaultPoolId').value.trim();

  if (!serverUrl || !apiKey) {
    showStatus('error', '请填写服务器地址和 API Key');
    return;
  }

  await chrome.storage.sync.set({ serverUrl, apiKey, defaultPoolId });
  showStatus('success', '配置已保存！');
}

async function testConnection() {
  const serverUrl = document.getElementById('serverUrl').value.trim().replace(/\/$/, '');
  const apiKey = document.getElementById('apiKey').value.trim();

  if (!serverUrl || !apiKey) {
    showStatus('error', '请先填写服务器地址和 API Key');
    return;
  }

  showStatus('info', '正在测试连接...');

  try {
    const resp = await fetch(`${serverUrl}/api/v1/system/version`, {
      headers: { 'X-API-Key': apiKey }
    });
    if (resp.ok) {
      const data = await resp.json();
      showStatus('success', `连接成功！服务器版本: v${data.current}`);
    } else {
      const err = await resp.json();
      showStatus('error', `连接失败: ${err.detail || `HTTP ${resp.status}`}`);
    }
  } catch (e) {
    showStatus('error', `连接失败: ${e.message}`);
  }
}

function showStatus(type, msg) {
  const el = document.getElementById('status');
  el.className = `status ${type}`;
  el.textContent = msg;
  el.style.display = 'block';
}
