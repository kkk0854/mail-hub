// MAIL HUB 浏览器扩展 - Background Service Worker
chrome.runtime.onInstalled.addListener(() => {
  console.log('MAIL HUB 助手已安装');
});

// 监听来自 popup 的消息
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === 'getConfig') {
    chrome.storage.sync.get(['serverUrl', 'apiKey', 'defaultPoolId'], (config) => {
      sendResponse(config);
    });
    return true; // 异步响应
  }
});
