/**
 * GSports — Chat Widget (Vanilla JS)
 *
 * Quản lý:
 *  - Toggle widget (mở/đóng panel)
 *  - Load danh sách phòng chat
 *  - Vào phòng chat → load lịch sử + mở WebSocket
 *  - Gửi/nhận tin nhắn realtime
 *  - Auto-reconnect WebSocket
 */

(function () {
    'use strict';

    // ─── DOM References ─────────────────────────────────────────
    const bubble       = document.getElementById('chat-bubble');
    const badge        = document.getElementById('chat-badge');
    const panel        = document.getElementById('chat-panel');
    const backBtn      = document.getElementById('chat-back-btn');
    const closeBtn     = document.getElementById('chat-close-btn');
    const headerTitle  = document.getElementById('chat-header-title');
    const roomList     = document.getElementById('chat-room-list');
    const roomListContent = document.getElementById('chat-room-list-content');
    const roomListEmpty = document.getElementById('chat-room-list-empty');
    const roomView     = document.getElementById('chat-room-view');
    const messagesEl   = document.getElementById('chat-messages');
    const inputText    = document.getElementById('chat-input-text');
    const sendBtn      = document.getElementById('chat-send-btn');

    // ─── State ──────────────────────────────────────────────────
    const userId = window.CHAT_USER_ID;
    let chatSocket     = null;
    let currentRoomId  = null;
    let reconnectTimer = null;
    let reconnectDelay = 1000;

    // ─── CSRF Token ─────────────────────────────────────────────
    function getCsrfToken() {
        const cookie = document.cookie.split(';').find(c => c.trim().startsWith('csrftoken='));
        return cookie ? cookie.split('=')[1] : '';
    }

    // ─── Toggle Panel ───────────────────────────────────────────
    function togglePanel() {
        const isHidden = panel.classList.contains('chat-panel--hidden');
        if (isHidden) {
            panel.classList.remove('chat-panel--hidden');
            loadRoomList();
        } else {
            panel.classList.add('chat-panel--hidden');
        }
    }

    function closePanel() {
        panel.classList.add('chat-panel--hidden');
        if (chatSocket) {
            chatSocket.close();
            chatSocket = null;
        }
        currentRoomId = null;
    }

    // ─── Navigation ─────────────────────────────────────────────
    function showRoomList() {
        roomList.style.display = '';
        roomView.style.display = 'none';
        backBtn.style.display = 'none';
        headerTitle.textContent = 'Tin nhắn';

        if (chatSocket) {
            chatSocket.close();
            chatSocket = null;
        }
        currentRoomId = null;
        loadRoomList();
    }

    function showRoomView(roomId, roomName) {
        roomList.style.display = 'none';
        roomView.style.display = '';
        backBtn.style.display = '';
        headerTitle.textContent = roomName;
        currentRoomId = roomId;

        messagesEl.innerHTML = '';
        loadMessages(roomId);
        connectWebSocket(roomId);
    }

    // ─── Load Room List ─────────────────────────────────────────
    function loadRoomList() {
        fetch('/api/chat/rooms/', {
            credentials: 'same-origin',
        })
        .then(function (res) { return res.json(); })
        .then(function (data) {
            renderRoomList(data.rooms || []);
        })
        .catch(function (err) {
            console.error('[Chat] Load rooms error:', err);
        });
    }

    function renderRoomList(rooms) {
        roomListContent.innerHTML = '';

        if (rooms.length === 0) {
            roomListEmpty.style.display = '';
            return;
        }
        roomListEmpty.style.display = 'none';

        rooms.forEach(function (room) {
            var displayName = room.venue_name;
            // Nếu user là owner/staff → hiện tên customer
            if (room.customer_id !== userId) {
                displayName = room.customer_name;
            }

            var initial = displayName.charAt(0).toUpperCase();
            var preview = room.last_message
                ? room.last_message.text
                : 'Chưa có tin nhắn';
            var time = room.last_message
                ? room.last_message.created_at
                : '';

            var item = document.createElement('div');
            item.className = 'chat-room-item';
            item.setAttribute('data-room-id', room.id);
            item.innerHTML =
                '<div class="chat-room-item__avatar">' + initial + '</div>' +
                '<div class="chat-room-item__info">' +
                    '<div class="chat-room-item__name">' + escapeHtml(displayName) + '</div>' +
                    '<div class="chat-room-item__preview">' + escapeHtml(preview) + '</div>' +
                '</div>' +
                (time ? '<span class="chat-room-item__time">' + escapeHtml(time) + '</span>' : '');

            item.addEventListener('click', function () {
                showRoomView(room.id, displayName);
            });

            roomListContent.appendChild(item);
        });
    }

    // ─── Load Messages ──────────────────────────────────────────
    function loadMessages(roomId) {
        fetch('/api/chat/rooms/' + roomId + '/messages/', {
            credentials: 'same-origin',
        })
        .then(function (res) { return res.json(); })
        .then(function (data) {
            renderMessages(data.messages || []);
            scrollToBottom();
        })
        .catch(function (err) {
            console.error('[Chat] Load messages error:', err);
        });
    }

    function renderMessages(messages) {
        messages.forEach(function (msg) {
            appendMessage(msg, false);
        });
    }

    function appendMessage(msg, animate) {
        var isMine = msg.sender_id === userId;

        var wrapper = document.createElement('div');
        wrapper.className = 'chat-msg ' + (isMine ? 'chat-msg--mine' : 'chat-msg--other');

        var html = '';
        if (!isMine) {
            html += '<span class="chat-msg__sender">' + escapeHtml(msg.sender_name) + '</span>';
        }
        html += '<div class="chat-msg__bubble">' + escapeHtml(msg.message_text) + '</div>';
        html += '<span class="chat-msg__time">' + escapeHtml(msg.created_at) + '</span>';

        wrapper.innerHTML = html;

        if (!animate) {
            wrapper.style.animation = 'none';
        }

        messagesEl.appendChild(wrapper);
    }

    function scrollToBottom() {
        messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    // ─── WebSocket ──────────────────────────────────────────────
    function connectWebSocket(roomId) {
        if (chatSocket) {
            chatSocket.close();
        }

        var wsScheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
        var wsUrl = wsScheme + '://' + window.location.host + '/ws/chat/' + roomId + '/';

        chatSocket = new WebSocket(wsUrl);

        chatSocket.onopen = function () {
            reconnectDelay = 1000;
            console.log('[Chat] WebSocket connected:', roomId);
        };

        chatSocket.onmessage = function (e) {
            try {
                var msg = JSON.parse(e.data);
                // Chỉ append nếu đang ở đúng room
                if (currentRoomId === msg.room_id || currentRoomId === roomId) {
                    appendMessage(msg, true);
                    scrollToBottom();
                }
            } catch (err) {
                console.error('[Chat] Parse error:', err);
            }
        };

        chatSocket.onclose = function (e) {
            console.log('[Chat] WebSocket closed:', e.code);
            // Auto-reconnect nếu đang ở trong room
            if (currentRoomId === roomId) {
                reconnectTimer = setTimeout(function () {
                    console.log('[Chat] Reconnecting...');
                    connectWebSocket(roomId);
                    reconnectDelay = Math.min(reconnectDelay * 2, 10000);
                }, reconnectDelay);
            }
        };

        chatSocket.onerror = function (err) {
            console.error('[Chat] WebSocket error:', err);
        };
    }

    // ─── Send Message ───────────────────────────────────────────
    function sendMessage() {
        var text = inputText.value.trim();
        if (!text || !chatSocket || chatSocket.readyState !== WebSocket.OPEN) {
            return;
        }

        chatSocket.send(JSON.stringify({ message: text }));
        inputText.value = '';
        inputText.style.height = 'auto';
        inputText.focus();
    }

    // ─── Utilities ──────────────────────────────────────────────
    function escapeHtml(str) {
        var div = document.createElement('div');
        div.appendChild(document.createTextNode(str));
        return div.innerHTML;
    }

    // ─── Auto-resize textarea ───────────────────────────────────
    function autoResize() {
        inputText.style.height = 'auto';
        inputText.style.height = Math.min(inputText.scrollHeight, 100) + 'px';
    }

    // ─── Event Listeners ────────────────────────────────────────
    bubble.addEventListener('click', togglePanel);
    closeBtn.addEventListener('click', closePanel);
    backBtn.addEventListener('click', showRoomList);
    sendBtn.addEventListener('click', sendMessage);

    inputText.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    inputText.addEventListener('input', autoResize);

})();
