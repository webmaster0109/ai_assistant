import { startTransition, useEffect, useMemo, useRef, useState } from "react";

const rootElement = document.getElementById("root");
const initialBranding = {
  website_name: rootElement?.dataset.siteName || "Ollama AI",
  website_description:
    rootElement?.dataset.siteDescription ||
    "A focused workspace for your private AI conversations.",
  website_favicon: rootElement?.dataset.siteFavicon || "",
};

function getCsrfToken() {
  const cookie = document.cookie
    .split("; ")
    .find((item) => item.startsWith("csrftoken="));
  return cookie ? decodeURIComponent(cookie.split("=")[1]) : "";
}

async function apiRequest(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const method = (options.method || "GET").toUpperCase();
  const hasBody = options.body !== undefined;

  if (hasBody && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  if (method !== "GET" && method !== "HEAD" && !headers.has("X-CSRFToken")) {
    headers.set("X-CSRFToken", getCsrfToken());
  }

  const response = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers,
  });

  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? await response.json()
    : null;

  if (!response.ok) {
    const error = new Error(payload?.detail || "Something went wrong.");
    error.status = response.status;
    throw error;
  }

  return payload;
}

function formatTimestamp(value) {
  if (!value) {
    return "";
  }

  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatTokenCount(value) {
  if (!value) {
    return "0";
  }
  if (value >= 1000000) {
    return `${(value / 1000000).toFixed(1)}M`;
  }
  if (value >= 1000) {
    return `${(value / 1000).toFixed(1)}K`;
  }
  return String(value);
}

function decodeHtmlEntities(value) {
  if (!value) {
    return "";
  }

  const parser = new DOMParser();
  const doc = parser.parseFromString(`<!doctype html><body>${value}`, "text/html");
  return doc.body.textContent || "";
}

function languageFromAttributes(value) {
  const attrs = String(value || "");
  const languageMatch = attrs.match(/language-([\w.+-]+)/i) || attrs.match(/lang-([\w.+-]+)/i);
  return languageMatch ? languageMatch[1].toLowerCase() : "";
}

function convertHtmlCodeBlocksToFences(value) {
  let source = String(value || "");

  source = source.replace(
    /<pre\b([^>]*)>\s*<code\b([^>]*)>([\s\S]*?)<\/code>\s*<\/pre>/gi,
    (_, preAttrs, codeAttrs, codeContent) => {
      const language = languageFromAttributes(`${preAttrs} ${codeAttrs}`);
      const decodedCode = decodeHtmlEntities(codeContent).replace(/\u00a0/g, " ").trim();
      return `\n\`\`\`${language}\n${decodedCode}\n\`\`\`\n`;
    },
  );

  source = source.replace(/<pre\b([^>]*)>([\s\S]*?)<\/pre>/gi, (_, preAttrs, codeContent) => {
    const language = languageFromAttributes(preAttrs);
    const decodedCode = decodeHtmlEntities(codeContent).replace(/\u00a0/g, " ").trim();
    return `\n\`\`\`${language}\n${decodedCode}\n\`\`\`\n`;
  });

  return source;
}

function normalizeAssistantSource(value) {
  if (!value) {
    return "";
  }

  return convertHtmlCodeBlocksToFences(value)
    .replace(/<\s*br\s*\/?>/gi, "\n")
    .replace(/<\s*li[^>]*>/gi, "- ")
    .replace(/<\/\s*(p|div|li|ul|ol|h[1-6]|tr)\s*>/gi, "\n")
    .replace(/&nbsp;/gi, " ")
    .replace(/&quot;/gi, "\"")
    .replace(/&#39;|&#x27;/gi, "'")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">")
    .replace(/&amp;/gi, "&");
}

function sanitizeAssistantText(value) {
  if (!value) {
    return "";
  }

  const normalized = normalizeAssistantSource(value);

  const parser = new DOMParser();
  const doc = parser.parseFromString(normalized, "text/html");
  const text = doc.body.textContent || "";

  return text
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/^\s*[-*]{3,}\s*$/gm, "")
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/__(.*?)__/g, "$1")
    .replace(/\*(.*?)\*/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/^\s*[-*]\s+/gm, "• ")
    .replace(/^\s*(\d+\.)\s+/gm, "$1 ")
    .replace(/\r\n?/g, "\n")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n[ \t]+/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function isLikelyCodeLine(line) {
  const trimmed = line.trim();
  if (!trimmed) {
    return false;
  }

  if (/^[-*]\s+/.test(trimmed) || /^\d+\.\s+/.test(trimmed)) {
    return false;
  }

  return (
    /^(def|class|from|import|return|if|elif|else:|for|while|try:|except|finally:|with|pass|raise|async|await|const|let|var|function|interface|type|public|private|protected|urlpatterns|path\(|router\.|SELECT|INSERT|UPDATE|DELETE)\b/.test(trimmed)
    || /^[A-Za-z_][\w.]*\s*=\s*.+/.test(trimmed)
    || /^{%.*%}$/.test(trimmed)
    || /^{{.*}}$/.test(trimmed)
    || /[{};]$/.test(trimmed)
    || /=>/.test(trimmed)
    || /\bself\./.test(trimmed)
    || /\brequest\./.test(trimmed)
    || /\b.objects\./.test(trimmed)
    || /^\s{2,}\S/.test(line)
    || /^<\/?[A-Za-z][^>]*>$/.test(trimmed)
  );
}

function detectCodeLanguage(block) {
  if (/(^|\n)\s*(def |class |from |import |elif |except |self\.|pass$|try:)/.test(block)) {
    return "python";
  }
  if (/(^|\n)\s*(const |let |var |function |import |export |=>)/.test(block)) {
    return "javascript";
  }
  if (/(^|\n)\s*<[/A-Za-z!][^>]*>/.test(block)) {
    return "html";
  }
  if (/(^|\n)\s*[{[]/.test(block) && /"\w+"\s*:/.test(block)) {
    return "json";
  }
  return "";
}

function parseLooseAssistantBlocks(value) {
  const normalized = normalizeAssistantSource(value)
    .replace(/\r\n?/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();

  if (!normalized) {
    return [];
  }

  const blocks = normalized.split(/\n{2,}/).map((block) => block.trim()).filter(Boolean);

  return blocks.flatMap((block) => {
    const lines = block.split("\n");
    const codeLineCount = lines.filter(isLikelyCodeLine).length;
    const isCodeBlock = lines.length >= 3 && codeLineCount >= Math.max(2, Math.ceil(lines.length / 2));

    if (isCodeBlock) {
      return [{
        type: "code",
        language: detectCodeLanguage(block),
        content: block,
      }];
    }

    const text = sanitizeAssistantText(block);
    return text ? [{ type: "text", content: text }] : [];
  });
}

function parseAssistantMessage(value) {
  const source = normalizeAssistantSource(value);
  const segments = [];
  const fencePattern = /```([\w.+-]*)\n?([\s\S]*?)```/g;
  let lastIndex = 0;
  let match = fencePattern.exec(source);

  while (match) {
    segments.push(...parseLooseAssistantBlocks(source.slice(lastIndex, match.index)));

    const code = match[2].replace(/^\n+|\n+$/g, "");
    if (code) {
      segments.push({
        type: "code",
        language: (match[1] || "").trim(),
        content: code,
      });
    }

    lastIndex = fencePattern.lastIndex;
    match = fencePattern.exec(source);
  }

  segments.push(...parseLooseAssistantBlocks(source.slice(lastIndex)));

  if (!segments.length) {
    return [{ type: "text", content: sanitizeAssistantText(source) }];
  }

  return segments;
}

function copyText(value) {
  if (navigator.clipboard?.writeText) {
    return navigator.clipboard.writeText(value);
  }

  const textArea = document.createElement("textarea");
  textArea.value = value;
  textArea.setAttribute("readonly", "");
  textArea.style.position = "absolute";
  textArea.style.left = "-9999px";
  document.body.appendChild(textArea);
  textArea.select();
  document.execCommand("copy");
  document.body.removeChild(textArea);
  return Promise.resolve();
}

function CodeBlock({ language, code }) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) {
      return undefined;
    }

    const timer = window.setTimeout(() => setCopied(false), 1800);
    return () => window.clearTimeout(timer);
  }, [copied]);

  async function handleCopy() {
    try {
      await copyText(code);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="message-code">
      <div className="message-code-toolbar">
        <span className="message-code-language">{language || "Code"}</span>
        <button
          className="message-code-copy"
          type="button"
          onClick={handleCopy}
          title={copied ? "Copied" : "Copy code"}
          aria-label={copied ? "Copied" : "Copy code"}
        >
          <i className={`bi ${copied ? "bi-check2" : "bi-copy"}`} />
        </button>
      </div>
      <pre className="message-code-pre">
        <code>{code}</code>
      </pre>
    </div>
  );
}

function AssistantMessageContent({ value }) {
  const segments = useMemo(() => parseAssistantMessage(value), [value]);

  return (
    <div className="assistant-content">
      {segments.map((segment, index) =>
        segment.type === "code" ? (
          <CodeBlock
            key={`${segment.language}-${index}`}
            language={segment.language}
            code={segment.content}
          />
        ) : (
          <div className="message-body" key={`text-${index}`}>
            {segment.content}
          </div>
        ),
      )}
    </div>
  );
}

function syncDocumentBranding(branding) {
  document.title = branding.website_name || "Ollama AI";

  let favicon = document.querySelector("#app-favicon")
    || document.querySelector("link[rel='icon']")
    || document.querySelector("link[rel='shortcut icon']");
  if (!favicon) {
    favicon = document.createElement("link");
    favicon.setAttribute("rel", "icon");
    favicon.setAttribute("id", "app-favicon");
    document.head.appendChild(favicon);
  }

  if (branding.website_favicon) {
    favicon.setAttribute("href", branding.website_favicon);
  }
}

function getInitialTheme() {
  const storedTheme = window.localStorage.getItem("ui-theme");
  if (storedTheme === "light" || storedTheme === "dark") {
    return storedTheme;
  }
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function ThemeToggle({ theme, onToggle }) {
  const nextTheme = theme === "dark" ? "light" : "dark";
  return (
    <button
      className="theme-toggle"
      type="button"
      onClick={onToggle}
      title={`Switch to ${nextTheme} mode`}
      aria-label={`Switch to ${nextTheme} mode`}
    >
      <i className={`bi ${theme === "dark" ? "bi-sun-fill" : "bi-moon-stars-fill"}`} />
    </button>
  );
}

function ToastViewport({ toasts, onDismiss }) {
  return (
    <div className="toast-viewport" aria-live="polite" aria-atomic="true">
      {toasts.map((toast) => (
        <div className={`toast toast-${toast.type}`} key={toast.id}>
          <div className="toast-icon">
            <i
              className={`bi ${
                toast.type === "success"
                  ? "bi-check2-circle"
                  : toast.type === "error"
                    ? "bi-exclamation-octagon"
                    : "bi-info-circle"
              }`}
            />
          </div>
          <div className="toast-content">
            <strong>{toast.title}</strong>
            <p>{toast.message}</p>
          </div>
          <button
            className="toast-close"
            type="button"
            onClick={() => onDismiss(toast.id)}
            aria-label="Dismiss notification"
          >
            <i className="bi bi-x-lg" />
          </button>
          <div className="toast-timer" />
        </div>
      ))}
    </div>
  );
}

function BrandIdentity({ branding, subtitle, compact = false }) {
  return (
    <div className={`brand-identity ${compact ? "compact" : ""}`}>
      {branding.website_favicon ? (
        <img className="brand-mark" src={branding.website_favicon} alt={`${branding.website_name} icon`} />
      ) : (
        <div className="brand-mark placeholder">{branding.website_name.slice(0, 1)}</div>
      )}
      <div className="brand-copy">
        <span className="brand-name">{branding.website_name}</span>
        <span className="brand-subtitle">{subtitle}</span>
      </div>
    </div>
  );
}

function SidebarNav({ currentPage, onOpenChats, onOpenProfile }) {
  return (
    <div className="sidebar-nav">
      <button
        className={`nav-chip ${currentPage === "chat" ? "active" : ""}`}
        type="button"
        onClick={onOpenChats}
      >
        <i className="bi bi-chat-square-text" />
        Chats
      </button>
      <button
        className={`nav-chip ${currentPage === "profile" ? "active" : ""}`}
        type="button"
        onClick={onOpenProfile}
      >
        <i className="bi bi-person-circle" />
        Profile
      </button>
    </div>
  );
}

function AuthPanel({
  branding,
  mode,
  form,
  loading,
  theme,
  onThemeToggle,
  onModeChange,
  onFormChange,
  onSubmit,
}) {
  const isRegister = mode === "register";

  return (
    <div className="auth-shell">
      <section className="auth-hero">
        <div className="auth-hero-panel">
          <div className="panel-topline">
            <BrandIdentity
              branding={branding}
              subtitle="Private assistant workspace"
              compact
            />
            <ThemeToggle theme={theme} onToggle={onThemeToggle} />
          </div>
          <p className="eyebrow">Personal AI Workspace</p>
          <h1>{branding.website_name}</h1>
          <p className="auth-copy">{branding.website_description}</p>
          <p className="micro-copy">Private conversations, simple workspace, no shared history.</p>
          <div className="feature-grid">
            <article>
              <h2>Private by default</h2>
              <p>Chats are scoped to each user account, so no one else can see your conversation history.</p>
            </article>
            <article>
              <h2>Clean daily workflow</h2>
              <p>A quieter interface keeps the focus on your assistant instead of the chrome around it.</p>
            </article>
            <article>
              <h2>Backend-connected</h2>
              <p>Your existing Django and Ollama pipeline stays in place while the frontend experience is upgraded.</p>
            </article>
          </div>
        </div>
      </section>

      <section className="auth-card">
        <div className="auth-card-inner">
          <p className="eyebrow">{isRegister ? "Create account" : "Welcome back"}</p>
          <h2>{isRegister ? "Start your private workspace" : "Sign in to continue"}</h2>
          <p className="auth-subcopy">
            {isRegister
              ? "Register once to keep your chats separate and secure."
              : "Login is required before you can access chat history or send prompts."}
          </p>
          <p className="fine-print">
            Small, focused, and private. Your account keeps its own conversations and settings.
          </p>

          <form className="auth-form" onSubmit={onSubmit}>
            {isRegister ? (
              <label>
                <span>Username</span>
                <input
                  name="username"
                  value={form.username}
                  onChange={onFormChange}
                  placeholder="your-username"
                  autoComplete="username"
                  required
                />
              </label>
            ) : null}

            {isRegister ? (
              <label>
                <span>Email</span>
                <input
                  type="email"
                  name="email"
                  value={form.email}
                  onChange={onFormChange}
                  placeholder="you@example.com"
                  autoComplete="email"
                  required
                />
              </label>
            ) : null}

            {!isRegister ? (
              <label>
                <span>Email or username</span>
                <input
                  name="identifier"
                  value={form.identifier}
                  onChange={onFormChange}
                  placeholder="you@example.com"
                  autoComplete="username"
                  required
                />
              </label>
            ) : null}

            <label>
              <span>Password</span>
              <input
                type="password"
                name="password"
                value={form.password}
                onChange={onFormChange}
                placeholder="Enter a secure password"
                autoComplete={isRegister ? "new-password" : "current-password"}
                required
              />
            </label>

            {isRegister ? (
              <label>
                <span>Confirm password</span>
                <input
                  type="password"
                  name="password_confirm"
                  value={form.password_confirm}
                  onChange={onFormChange}
                  placeholder="Repeat your password"
                  autoComplete="new-password"
                  required
                />
              </label>
            ) : null}

            <button className="primary-button" type="submit" disabled={loading}>
              {loading ? "Working..." : isRegister ? "Create account" : "Sign in"}
            </button>
          </form>

          <button
            className="text-button"
            type="button"
            onClick={() => onModeChange(isRegister ? "login" : "register")}
          >
            {isRegister
              ? "Already have an account? Sign in"
              : "Need an account? Register"}
          </button>
        </div>
      </section>
    </div>
  );
}

function WorkspaceOverview({ activeSession, sessions, usage }) {
  const summaryItems = [
    {
      label: "Current model",
      value: activeSession?.model || "Select for new chat",
      note: "Locked once a conversation starts.",
    },
    {
      label: "Private chats",
      value: String(sessions.length),
      note: "Visible only to the signed-in user.",
    },
    {
      label: "Token total",
      value: formatTokenCount(usage.total_tokens),
      note: "Usage shown for this account only.",
    },
  ];

  return (
    <section className="workspace-overview">
      {summaryItems.map((item) => (
        <article key={item.label} className="overview-card">
          <span className="overview-label">{item.label}</span>
          <strong className="overview-value">{item.value}</strong>
          <p className="small-note">{item.note}</p>
        </article>
      ))}
    </section>
  );
}

function SessionList({
  sessions,
  activeSessionId,
  currentPage,
  sidebarOpen,
  onNewChat,
  onClose,
  onOpenChats,
  onOpenProfile,
  onSelect,
  onDelete,
}) {
  return (
    <aside className={`sidebar ${sidebarOpen ? "is-open" : ""}`}>
      <div className="sidebar-block">
        <div className="sidebar-mobile-head">
          <p className="eyebrow">Workspace</p>
          <button
            className="secondary-button icon-button sidebar-mobile-close"
            type="button"
            onClick={onClose}
            aria-label="Close sidebar"
            title="Close sidebar"
          >
            <i className="bi bi-x-lg" />
          </button>
        </div>
        <p className="small-note">Your recent private chats live here.</p>
        <SidebarNav
          currentPage={currentPage}
          onOpenChats={onOpenChats}
          onOpenProfile={onOpenProfile}
        />
        <button className="primary-button full-width" type="button" onClick={onNewChat}>
          <i className="bi bi-plus-lg" />
          New chat
        </button>
      </div>

      <div className="sidebar-block sidebar-sessions">
        <div className="section-heading">
          <span>Recent chats</span>
          <span>{sessions.length}</span>
        </div>
        {sessions.length ? (
          sessions.map((session) => (
            <article
              key={session.id}
              className={`session-card ${session.id === activeSessionId ? "active" : ""}`}
            >
              <button
                className="session-main"
                type="button"
                onClick={() => onSelect(session.id)}
              >
                <span className="session-title">{session.title}</span>
                <span className="session-meta">
                  {session.model} • {formatTimestamp(session.updated_at)}
                </span>
                <span className="session-preview">{session.preview || "No messages yet."}</span>
              </button>
              <button
                className="session-delete icon-button"
                type="button"
                onClick={() => onDelete(session.id)}
                aria-label={`Delete ${session.title}`}
                title={`Delete ${session.title}`}
              >
                <i className="bi bi-trash3" />
              </button>
            </article>
          ))
        ) : (
          <div className="empty-card">
            <p>Your private chat history will appear here after the first message.</p>
          </div>
        )}
      </div>
    </aside>
  );
}

function UsageCard({ usage }) {
  return (
    <section className="usage-card">
      <div className="section-heading">
        <span><i className="bi bi-bar-chart-line" /> Usage</span>
        <span>Private totals</span>
      </div>
      <p className="small-note">Counts are scoped to the signed-in account only.</p>
      <div className="usage-grid">
        <article>
          <span>Input</span>
          <strong>{formatTokenCount(usage.total_input_tokens)}</strong>
        </article>
        <article>
          <span>Output</span>
          <strong>{formatTokenCount(usage.total_output_tokens)}</strong>
        </article>
        <article>
          <span>Total</span>
          <strong>{formatTokenCount(usage.total_tokens)}</strong>
        </article>
      </div>
    </section>
  );
}

function ProfilePage({ currentUser, usage, sessions }) {
  return (
    <div className="profile-page">
      <section className="profile-hero">
        <p className="eyebrow">Profile</p>
        <h1>{currentUser.username}</h1>
        <p className="workspace-subtitle">
          Personal usage and account details for this signed-in user only.
        </p>
        <p className="fine-print">
          This page is private to the current account and keeps usage data separate from every
          other user.
        </p>
      </section>

      <section className="profile-grid">
        <article className="profile-card">
          <span className="overview-label"><i className="bi bi-envelope" /> Email</span>
          <strong className="overview-value profile-value">{currentUser.email || "No email set"}</strong>
          <p className="small-note">Used for account identity and private access.</p>
        </article>
        <article className="profile-card">
          <span className="overview-label"><i className="bi bi-clock-history" /> Saved chats</span>
          <strong className="overview-value profile-value">{sessions.length}</strong>
          <p className="small-note">Only this user can see these conversations.</p>
        </article>
      </section>

      <UsageCard usage={usage} />
    </div>
  );
}

function ChatComposer({
  draft,
  model,
  models,
  isLocked,
  sending,
  onDraftChange,
  onModelChange,
  onDraftKeyDown,
  onSubmit,
}) {
  return (
    <form className="composer" onSubmit={onSubmit}>
      <div className="composer-inline">
        <label className="model-picker model-picker-inline">
          <div className="model-picker-shell">
            <i className="bi bi-cpu model-picker-icon" />
            <select
              value={model}
              onChange={onModelChange}
              disabled={isLocked || sending}
              aria-label="Model"
            >
              {models.map((item) => (
                <option key={item.key} value={item.key}>
                  {item.label}
                </option>
              ))}
            </select>
            <i className="bi bi-chevron-down model-picker-caret" />
          </div>
        </label>
        <div className="composer-input-wrap">
          <textarea
            value={draft}
            onChange={onDraftChange}
            onKeyDown={onDraftKeyDown}
            placeholder="Ask your assistant anything..."
            rows={1}
            disabled={sending}
          />
        </div>
        <button className="primary-button composer-button" type="submit" disabled={sending}>
          <i className={`bi ${sending ? "bi-arrow-repeat" : "bi-send"}`} />
          {sending ? "Sending..." : "Send"}
        </button>
      </div>
    </form>
  );
}

function MessageList({ branding, messages, pendingPrompt, loadingConversation }) {
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, pendingPrompt, loadingConversation]);

  if (loadingConversation) {
    return (
      <div className="message-empty">
        <p>Loading your conversation...</p>
      </div>
    );
  }

  if (!messages.length && !pendingPrompt) {
    return (
      <div className="message-empty">
        <p className="eyebrow">Ready when you are</p>
        <h2>Start a calmer, more focused chat.</h2>
        <p>
          Your assistant is connected to the existing backend, and each account keeps a separate
          private history.
        </p>
      </div>
    );
  }

  return (
    <div className="message-list">
      {messages.map((message) => (
        <div className="message-pair" key={message.id}>
          <article className="message-bubble user">
            <header>
              <span>You</span>
              <time>{formatTimestamp(message.created_at)}</time>
            </header>
            <div className="message-body">{message.user_message}</div>
          </article>
          <article className="message-bubble assistant">
            <header>
              <span>{branding.website_name}</span>
            </header>
            <AssistantMessageContent value={message.ai_message} />
          </article>
        </div>
      ))}

      {pendingPrompt ? (
        <div className="message-pair pending">
          <article className="message-bubble user">
            <header>
              <span>You</span>
            </header>
            <div className="message-body">{pendingPrompt}</div>
          </article>
          <article className="message-bubble assistant">
            <header>
              <span>{branding.website_name}</span>
            </header>
            <div className="message-body subtle">Thinking...</div>
          </article>
        </div>
      ) : null}
      <div ref={bottomRef} />
    </div>
  );
}

export default function App() {
  const [theme, setTheme] = useState(getInitialTheme);
  const [currentPage, setCurrentPage] = useState("chat");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [branding, setBranding] = useState(initialBranding);
  const [authReady, setAuthReady] = useState(false);
  const [currentUser, setCurrentUser] = useState(null);
  const [authMode, setAuthMode] = useState("login");
  const [authLoading, setAuthLoading] = useState(false);
  const [authForm, setAuthForm] = useState({
    username: "",
    identifier: "",
    email: "",
    password: "",
    password_confirm: "",
  });
  const [models, setModels] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [activeSessionId, setActiveSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [usage, setUsage] = useState({
    total_input_tokens: 0,
    total_output_tokens: 0,
    total_tokens: 0,
  });
  const [draft, setDraft] = useState("");
  const [selectedModel, setSelectedModel] = useState("");
  const [sending, setSending] = useState(false);
  const [loadingConversation, setLoadingConversation] = useState(false);
  const [pendingPrompt, setPendingPrompt] = useState("");
  const [toasts, setToasts] = useState([]);
  const toastIdRef = useRef(0);

  const activeSession = useMemo(
    () => sessions.find((session) => session.id === activeSessionId) || null,
    [sessions, activeSessionId],
  );

  function dismissToast(id) {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }

  function showToast(title, message, type = "info") {
    const id = toastIdRef.current + 1;
    toastIdRef.current = id;
    setToasts((current) => [...current, { id, title, message, type }]);
    window.setTimeout(() => {
      dismissToast(id);
    }, 5000);
  }

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    window.localStorage.setItem("ui-theme", theme);
  }, [theme]);

  useEffect(() => {
    syncDocumentBranding(branding);
  }, [branding]);

  useEffect(() => {
    async function bootstrap() {
      try {
        const [authPayload, modelPayload] = await Promise.all([
          apiRequest("/api/auth/me/"),
          apiRequest("/api/models/"),
        ]);

        setBranding(authPayload.branding || initialBranding);
        setModels(modelPayload.models || []);
        if ((modelPayload.models || []).length) {
          setSelectedModel((current) => current || modelPayload.models[0].key);
        }

        if (authPayload.authenticated) {
          setCurrentUser(authPayload.user);
          await loadWorkspace();
        }
      } catch (error) {
        showToast("Workspace issue", error.message, "error");
      } finally {
        setAuthReady(true);
      }
    }

    bootstrap();
  }, []);

  async function loadWorkspace() {
    const [sessionsPayload, usagePayload] = await Promise.all([
      apiRequest("/api/chat/sessions/"),
      apiRequest("/api/usage-stats/"),
    ]);

    setSessions(sessionsPayload.sessions || []);
    setUsage(usagePayload);

    if ((sessionsPayload.sessions || []).length === 0) {
      setActiveSessionId(null);
      setMessages([]);
      return;
    }

    if (!activeSessionId) {
      await handleSelectSession(sessionsPayload.sessions[0].id);
    }
  }

  async function refreshUsage() {
    try {
      const usagePayload = await apiRequest("/api/usage-stats/");
      setUsage(usagePayload);
    } catch (error) {
      if (error.status !== 401) {
        showToast("Usage unavailable", error.message, "error");
      }
    }
  }

  function resetWorkspace() {
    setSessions([]);
    setActiveSessionId(null);
    setCurrentPage("chat");
    setMessages([]);
    setUsage({
      total_input_tokens: 0,
      total_output_tokens: 0,
      total_tokens: 0,
    });
    setDraft("");
    setPendingPrompt("");
  }

  function handleAuthFormChange(event) {
    const { name, value } = event.target;
    setAuthForm((current) => ({ ...current, [name]: value }));
  }

  async function handleAuthSubmit(event) {
    event.preventDefault();
    setAuthLoading(true);

    try {
      const endpoint = authMode === "register" ? "/api/auth/register/" : "/api/auth/login/";
      const payload =
        authMode === "register"
          ? {
              username: authForm.username,
              email: authForm.email,
              password: authForm.password,
              password_confirm: authForm.password_confirm,
            }
          : {
              identifier: authForm.identifier,
              password: authForm.password,
            };

      const response = await apiRequest(endpoint, {
        method: "POST",
        body: JSON.stringify(payload),
      });

      setCurrentUser(response.user);
      resetWorkspace();
      await loadWorkspace();
      setAuthForm({
        username: "",
        identifier: "",
        email: "",
        password: "",
        password_confirm: "",
      });
      showToast(
        authMode === "register" ? "Registration complete" : "Login successful",
        authMode === "register"
          ? "Your private workspace is ready."
          : "Welcome back to your private workspace.",
        "success",
      );
    } catch (error) {
      showToast(
        authMode === "register" ? "Registration failed" : "Login failed",
        error.message,
        "error",
      );
    } finally {
      setAuthLoading(false);
    }
  }

  async function handleLogout() {
    try {
      await apiRequest("/api/auth/logout/", {
        method: "POST",
        body: JSON.stringify({}),
      });
      showToast("Logged out", "You have been signed out safely.", "success");
    } catch (error) {
      showToast("Logout issue", error.message, "error");
    } finally {
      setCurrentUser(null);
      resetWorkspace();
    }
  }

  async function handleSelectSession(sessionId) {
    setLoadingConversation(true);

    try {
      const payload = await apiRequest(`/api/chat/sessions/${sessionId}/messages/`);
      startTransition(() => {
        setCurrentPage("chat");
        setActiveSessionId(payload.session.id);
        setSelectedModel(payload.session.model);
        setMessages(payload.messages || []);
      });
    } catch (error) {
      showToast("Unable to open chat", error.message, "error");
    } finally {
      setLoadingConversation(false);
    }
  }

  async function handleDeleteSession(sessionId) {
    const confirmed = window.confirm("Delete this chat permanently?");
    if (!confirmed) {
      return;
    }

    try {
      await apiRequest(`/api/chat/sessions/${sessionId}/`, {
        method: "DELETE",
      });

      const remainingSessions = sessions.filter((session) => session.id !== sessionId);
      setSessions(remainingSessions);
      if (activeSessionId === sessionId) {
        setActiveSessionId(null);
        setMessages([]);
      }
      await refreshUsage();
      showToast("Chat deleted", "The conversation was removed.", "success");
    } catch (error) {
      showToast("Delete failed", error.message, "error");
    }
  }

  function handleNewChat() {
    setCurrentPage("chat");
    setSidebarOpen(false);
    setActiveSessionId(null);
    setMessages([]);
    setPendingPrompt("");
    showToast("New chat", "Start a fresh private conversation.", "info");
  }

  function handleDraftKeyDown(event) {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  }

  async function handleSendMessage(event) {
    event.preventDefault();
    const content = draft.trim();

    if (sending) {
      return;
    }

    if (!content) {
      showToast("Message required", "Write a message before sending.", "error");
      return;
    }

    setSending(true);
    setPendingPrompt(content);

    try {
      const payload = await apiRequest("/api/chat/", {
        method: "POST",
        body: JSON.stringify({
          message: content,
          model: activeSession?.model || selectedModel,
          session_id: activeSessionId,
        }),
      });

      setDraft("");
      setPendingPrompt("");
      setMessages((current) => [...current, payload.message]);
      setActiveSessionId(payload.session.id);
      setSelectedModel(payload.session.model);
      setSessions((current) => {
        const deduped = current.filter((session) => session.id !== payload.session.id);
        return [payload.session, ...deduped];
      });
      await refreshUsage();
    } catch (error) {
      setPendingPrompt("");
      if (error.status === 401) {
        showToast("Session expired", "Please sign in again to continue chatting.", "error");
        setCurrentUser(null);
        resetWorkspace();
        return;
      }
      showToast("Send failed", error.message, "error");
    } finally {
      setSending(false);
    }
  }

  if (!authReady) {
    return (
      <div className="loading-shell">
        <div className="loading-card">
          <p className="eyebrow">Loading workspace</p>
          <h1>{branding.website_name}</h1>
        </div>
      </div>
    );
  }

  if (!currentUser) {
    return (
      <>
        <ToastViewport toasts={toasts} onDismiss={dismissToast} />
        <AuthPanel
          branding={branding}
          mode={authMode}
          form={authForm}
          loading={authLoading}
          theme={theme}
          onThemeToggle={() => setTheme((current) => (current === "dark" ? "light" : "dark"))}
          onModeChange={setAuthMode}
          onFormChange={handleAuthFormChange}
          onSubmit={handleAuthSubmit}
        />
      </>
    );
  }

  return (
      <>
        <ToastViewport toasts={toasts} onDismiss={dismissToast} />
        {sidebarOpen ? (
          <button
            className="sidebar-backdrop"
            type="button"
            onClick={() => setSidebarOpen(false)}
            aria-label="Close sidebar"
          />
        ) : null}
        <div className="app-shell">
          <SessionList
            sessions={sessions}
            activeSessionId={activeSessionId}
            currentPage={currentPage}
            sidebarOpen={sidebarOpen}
            onNewChat={handleNewChat}
            onClose={() => setSidebarOpen(false)}
            onOpenChats={() => {
              setCurrentPage("chat");
              setSidebarOpen(false);
            }}
            onOpenProfile={() => {
              setCurrentPage("profile");
              setSidebarOpen(false);
            }}
            onSelect={(sessionId) => {
              setSidebarOpen(false);
              return handleSelectSession(sessionId);
            }}
            onDelete={handleDeleteSession}
          />

          <main className="workspace">
            <header className="workspace-header">
              <div className="workspace-heading">
                <button
                  className="secondary-button icon-button mobile-sidebar-toggle"
                  type="button"
                  onClick={() => setSidebarOpen((current) => !current)}
                  aria-label={sidebarOpen ? "Hide sidebar" : "Show sidebar"}
                  title={sidebarOpen ? "Hide sidebar" : "Show sidebar"}
                >
                  <i className={`bi ${sidebarOpen ? "bi-x-lg" : "bi-list"}`} />
                </button>
                <div className="workspace-heading-copy">
                  <p className="eyebrow">Authenticated workspace</p>
                  <h1>{currentPage === "profile" ? "Profile" : activeSession?.title || "New conversation"}</h1>
                  {currentPage === "profile" ? (
                    <p className="workspace-subtitle">
                      A separate page for this user’s account details and usage totals.
                    </p>
                  ) : null}
                </div>
              </div>

              <div className="workspace-actions">
                <ThemeToggle
                  theme={theme}
                  onToggle={() => setTheme((current) => (current === "dark" ? "light" : "dark"))}
                />
                <button
                  className="secondary-button icon-button"
                  type="button"
                  onClick={handleLogout}
                  title="Logout"
                  aria-label="Logout"
                >
                  <i className="bi bi-power" />
                </button>
              </div>
            </header>

            {currentPage === "profile" ? (
              <ProfilePage currentUser={currentUser} usage={usage} sessions={sessions} />
            ) : (
              <>
                <section className="conversation-panel">
                  <MessageList
                    branding={branding}
                    messages={messages}
                    pendingPrompt={pendingPrompt}
                    loadingConversation={loadingConversation}
                  />
                </section>

                <ChatComposer
                  draft={draft}
                  model={activeSession?.model || selectedModel}
                  models={models}
                  isLocked={Boolean(activeSession)}
                  sending={sending}
                  onDraftChange={(event) => setDraft(event.target.value)}
                  onDraftKeyDown={handleDraftKeyDown}
                  onModelChange={(event) => setSelectedModel(event.target.value)}
                  onSubmit={handleSendMessage}
                />
              </>
            )}
          </main>
        </div>
      </>
  );
}
