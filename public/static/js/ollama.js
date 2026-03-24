const chatBox = document.querySelector("#chat-message");
const form = document.querySelector("#chat-form");

let currentSessionId = localStorage.getItem("currentSessionId") || null;
let currentSessionModel = localStorage.getItem("currentSessionModel") || null;

function openSidebar() {
  document.querySelector("#sidebar").classList.add("open");
  document.querySelector("#sidebar-overlay").classList.add("open");
}

function closeSidebar() {
  document.querySelector("#sidebar").classList.remove("open");
  document.querySelector("#sidebar-overlay").classList.remove("open");
}

// ── Sidebar ───────────────────────────────────────────────────
function addSidebarSession(title, sessionId) {
  const sidebar = document.querySelector("#sidebar-sessions");
  if (!sidebar) return;

  // Avoid duplicates
  if (sidebar.querySelector(`[data-session-id="${sessionId}"]`)) return;

  const item = document.createElement("div");
  item.classList.add("sidebar-item");
  item.dataset.sessionId = sessionId;
  item.textContent = title || "Untitled";

  if (sessionId === currentSessionId) item.classList.add("active");

  let pressTimer;
  let isLongPress = false;

  item.addEventListener("contextmenu", function (e) {
      e.preventDefault();
      if (isLongPress) return;
      handleDelete();
  })

  item.addEventListener("touchstart", function (e) {
    isLongPress = false;
    pressTimer = setTimeout(() => {
      isLongPress = true;
      handleDelete();
    }, 600);
  });

  item.addEventListener("touchend", function (e) {
    clearTimeout(pressTimer);
  });

  item.addEventListener("touchmove", function (e) {
    clearTimeout(pressTimer);
  });

  function handleDelete() {
    const confirmDelete = confirm("Are you sure you want to delete this session?");
    if (confirmDelete) {
      deleteSession(sessionId);
      item.remove();
      if (sessionId === currentSessionId) {
        startNewChat();
      }
    }
  }

  item.addEventListener("click", () => {
    document
      .querySelectorAll(".sidebar-item")
      .forEach((el) => el.classList.remove("active"));
    item.classList.add("active");
    closeSidebar();
    loadSession(sessionId);
  });

  sidebar.prepend(item);
}

// ── Load all sessions into sidebar on page load ───────────────
async function loadAllSessions() {
  try {
    const response = await fetch("/chat/sessions/");
    if (!response.ok)
      throw new Error(`Sessions fetch failed: ${response.status}`);
    const sessions = await response.json();
    sessions.reverse().forEach((s) => addSidebarSession(s.title, s.id));

    // Restore last active session
    if (currentSessionId) loadSession(currentSessionId);

  } catch (err) {
    console.error("[loadAllSessions] Failed:", err);
  }
}

// ── Helpers ───────────────────────────────────────────────────
function clearChatWindow() {
  chatBox.innerHTML = "";
}

function createChatContainer() {
  const container = document.createElement("div");
  container.classList.add("chat-container");
  chatBox.appendChild(container);
  return container;
}

function appendMessages(userMessage, aiMessage, modelName) {
  const container = createChatContainer();
 
  const userMsg = document.createElement("p");
  userMsg.classList.add("user-message");
  userMsg.innerHTML = `<strong>USER: </strong>${userMessage}`;
  
  const aiMsg = document.createElement("div");
  aiMsg.classList.add("ai-message");
  aiMsg.innerHTML = `<strong>${modelName || "AI"}:</strong> ${aiMessage}`;
  
  container.appendChild(userMsg);
  container.appendChild(aiMsg);

  // console.log(container);
  chatBox.scrollTop = chatBox.scrollHeight;
}

function showLoading() {
  removeLoading();
  const loader = document.createElement("div");
  loader.id = "loading-indicator";
  loader.classList.add("chat-container");
  loader.innerHTML = '<em style="color:#888;">Rafat GenAI is thinking...</em>';
  chatBox.appendChild(loader);
  chatBox.scrollTop = chatBox.scrollHeight;
}

function removeLoading() {
  const loader = document.querySelector("#loading-indicator");
  if (loader) loader.remove();
}

// ── New chat ──────────────────────────────────────────────────
function startNewChat() {
  currentSessionId = null;
  currentSessionModel = null;
  localStorage.removeItem("currentSessionId");
  localStorage.removeItem("currentSessionModel");
  clearChatWindow();
  document
  .querySelectorAll(".sidebar-item")
  .forEach((el) => el.classList.remove("active"));
  closeSidebar();
  unlockModelDropdown();
}

// ── Send message ──────────────────────────────────────────────
form.addEventListener("submit", sendMessage);

// lock model selection when session is active
function lockModelDropdown(modelKey) {
  const modelSelect = document.querySelector("#model");
  modelSelect.value = modelKey;
  modelSelect.disabled = true;
  modelSelect.title = "Model is locked for this session. Start a new chat to change.";
  // document.querySelector('#lock-badge').classList.add('visible');
}

// unlock model dropdown when no active session
function unlockModelDropdown() {
  const modelSelect = document.querySelector("#model");
  modelSelect.disabled = false;
  modelSelect.title = "";
  // document.querySelector('#lock-badge').classList.remove('visible');
}

async function sendMessage(e) {
  e.preventDefault();

  const messageInput = document.querySelector("#message");
  const message = messageInput.value.trim();
  const popupDialog = document.querySelector("#popup-dialog");
  const popupContent = document.querySelector("#popup-content");
  const cancelBtn = document.querySelector("#cancel-btn");

  if (!message) {
    popupDialog.style.display = "flex";
    popupContent.innerHTML = "<p>Please enter a message first.</p>";
    cancelBtn.onclick = () => (popupDialog.style.display = "none");
    return;
  }

  const csrf_token = document.querySelector(
    'input[name="csrfmiddlewaretoken"]',
  ).value;
  const model = document.querySelector("#model").value;
  // const url = "{% url 'chat_post' %}";
  const url = "/chat/";

  messageInput.disabled = true;
  showLoading();

  try {
    const response = await fetch(url, {
      method: "POST",
      headers: { "X-CSRFToken": csrf_token },
      body: new URLSearchParams({
        message,
        model: currentSessionModel || model,
        session_id: currentSessionId || "",
        csrfmiddlewaretoken: csrf_token,
      }),
    });

    const result = await response.json();
    removeLoading();

    console.log("[sendMessage] result:", result); // ← debug

    if (response.ok) {
      if (!currentSessionId) {
        currentSessionId = result.session_id;
        currentSessionModel = result.model_key;
        localStorage.setItem("currentSessionId", currentSessionId);
        localStorage.setItem("currentSessionModel", currentSessionModel);
        addSidebarSession(result.title, result.session_id);
      }
      lockModelDropdown(currentSessionModel);
      appendMessages(result.user_message, result.ai_message, result.model);
      loadUsageStats();

      if (result.input_tokens || result.output_tokens) {
        updateUsageInstant(result.input_tokens, result.output_tokens);
      }

      messageInput.value = "";
    } else {
      console.error("[sendMessage] Server error:", result);
    }
  } catch (err) {
    removeLoading();
    console.error("[sendMessage] Fetch failed:", err);
  } finally {
    messageInput.disabled = false;
    messageInput.focus();
  }
}

function updateUsageInstant(inputTokens, outputTokens) {
    const currentTotal = parseInt(
        document.querySelector('#usage-total').textContent.replace(/[KM]/g, '') 
    ) || 0;

    // Just re-fetch — simplest approach
    loadUsageStats();
}

// ── Load session history ──────────────────────────────────────
async function loadSession(sessionId) {
  currentSessionId = sessionId;
  localStorage.setItem("currentSessionId", sessionId);
  clearChatWindow();
  showLoading();

  try {
    const response = await fetch(`/chat/history/${sessionId}/`);
    if (!response.ok)
      throw new Error(`History fetch failed: ${response.status}`);

    const conversations = await response.json();
    removeLoading();

    console.log("[loadSession] conversations:", conversations); // ← debug

    if (conversations.length > 0) {
      currentSessionModel = conversations[0].session__model;
      localStorage.setItem("currentSessionModel", currentSessionModel);
      lockModelDropdown(currentSessionModel);
    }

    if (conversations.length === 0) {
      chatBox.innerHTML =
        '<p style="color:#666; padding:20px;">No messages yet.</p>';
      return;
    }

    conversations.forEach((chat) =>
      appendMessages(chat.user_message, chat.ai_message, chat.session__model),
    );
  } catch (err) {
    removeLoading();
    console.error("[loadSession] Failed:", err);
  }
}

// ── Init — runs immediately since script is at bottom of body ─
loadAllSessions();
