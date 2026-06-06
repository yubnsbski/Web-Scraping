const API_BASE = '';

function query(sel) {
  return document.querySelector(sel);
}

function queryAll(sel) {
  return document.querySelectorAll(sel);
}

async function sendMessage(message) {
  if (!message.trim()) return;

  // ユーザーメッセージを表示
  appendChatMessage(message, 'user');
  query('#messageInput').value = '';

  try {
    // チャット API を呼び出し
    const response = await fetch(API_BASE + '/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message }),
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const data = await response.json();
    
    // AIレスポンスを表示
    appendChatMessage(data.content, 'assistant', data);
    
    // 追加データがあれば表示
    if (data.forecast_data) {
      displayForecastData(data.forecast_data);
    }
  } catch (e) {
    appendChatMessage(`エラー: ${e.message}`, 'system');
  }
}

function appendChatMessage(content, role, data = null) {
  const chatBox = query('#chatBox');
  const msg = document.createElement('div');
  msg.className = `chat-message ${role}`;

  let avatar = '';
  if (role === 'assistant') {
    avatar = '🤖';
  } else if (role === 'user') {
    avatar = '👤';
  } else {
    avatar = 'ℹ️';
  }

  msg.innerHTML = `
    <div class="message-avatar">${avatar}</div>
    <div class="message-content">${escapeHtml(content)}</div>
  `;

  chatBox.appendChild(msg);
  chatBox.scrollTop = chatBox.scrollHeight;
}

function displayForecastData(data) {
  const chatBox = query('#chatBox');
  const msg = document.createElement('div');
  msg.className = 'chat-message assistant';

  const html = `
    <div class="message-avatar">📊</div>
    <div class="message-content">
      <strong>予測データ:</strong><br/>
      直近リターン: ${data.last_observed_return.toFixed(2)}%<br/>
      現在値: $${data.last_observed_value.toFixed(2)}<br/>
      翌月予測: ${data.next_month_forecast.toFixed(2)}%<br/>
      信頼度: ${data.confidence}
    </div>
  `;

  msg.innerHTML = html;
  chatBox.appendChild(msg);
  chatBox.scrollTop = chatBox.scrollHeight;
}

function escapeHtml(text) {
  const map = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#039;',
  };
  return text.replace(/[&<>"']/g, m => map[m]);
}

function initializeChat() {
  // フォーム送信
  query('#chatForm').addEventListener('submit', (e) => {
    e.preventDefault();
    const msg = query('#messageInput').value.trim();
    if (msg) sendMessage(msg);
  });

  // サンプルボタン
  queryAll('.sample-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const prompt = btn.dataset.prompt;
      query('#messageInput').value = prompt;
      sendMessage(prompt);
    });
  });
}

window.addEventListener('DOMContentLoaded', initializeChat);
