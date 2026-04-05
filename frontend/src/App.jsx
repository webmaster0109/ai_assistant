import { Fragment, startTransition, useEffect, useMemo, useRef, useState } from "react";
import hljs from "highlight.js/lib/core";
import bash from "highlight.js/lib/languages/bash";
import css from "highlight.js/lib/languages/css";
import django from "highlight.js/lib/languages/django";
import javascript from "highlight.js/lib/languages/javascript";
import json from "highlight.js/lib/languages/json";
import python from "highlight.js/lib/languages/python";
import sql from "highlight.js/lib/languages/sql";
import typescript from "highlight.js/lib/languages/typescript";
import xml from "highlight.js/lib/languages/xml";
import yaml from "highlight.js/lib/languages/yaml";

hljs.registerLanguage("bash", bash);
hljs.registerLanguage("shell", bash);
hljs.registerLanguage("sh", bash);
hljs.registerLanguage("css", css);
hljs.registerLanguage("django", django);
hljs.registerLanguage("html", xml);
hljs.registerLanguage("xml", xml);
hljs.registerLanguage("javascript", javascript);
hljs.registerLanguage("js", javascript);
hljs.registerLanguage("json", json);
hljs.registerLanguage("python", python);
hljs.registerLanguage("py", python);
hljs.registerLanguage("sql", sql);
hljs.registerLanguage("typescript", typescript);
hljs.registerLanguage("ts", typescript);
hljs.registerLanguage("yaml", yaml);
hljs.registerLanguage("yml", yaml);

const rootElement = document.getElementById("root");
const initialBranding = {
  website_name: rootElement?.dataset.siteName || "Ollama AI",
  website_description:
    rootElement?.dataset.siteDescription ||
    "A focused workspace for your private AI conversations.",
  website_favicon: rootElement?.dataset.siteFavicon || "",
};
const MAX_DOCUMENT_UPLOAD_BYTES = 10 * 1024 * 1024;

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

async function apiFormRequest(path, formData, options = {}) {
  const headers = new Headers(options.headers || {});
  const method = (options.method || "POST").toUpperCase();

  if (method !== "GET" && method !== "HEAD" && !headers.has("X-CSRFToken")) {
    headers.set("X-CSRFToken", getCsrfToken());
  }

  const response = await fetch(path, {
    credentials: "same-origin",
    ...options,
    method,
    body: formData,
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

function parseSseBlock(block) {
  const lines = String(block || "").split("\n");
  let event = "message";
  const dataLines = [];

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();
    if (!line || line.startsWith(":")) {
      continue;
    }

    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
      continue;
    }

    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  }

  if (!dataLines.length) {
    return null;
  }

  return {
    event,
    payload: JSON.parse(dataLines.join("\n")),
  };
}

function getShareTokenFromPath() {
  const match = window.location.pathname.match(/^\/share\/([^/]+)\/?$/);
  return match ? match[1] : "";
}

function buildAbsoluteUrl(path) {
  if (!path) {
    return "";
  }
  return new URL(path, window.location.origin).href;
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

function sortSessions(list) {
  return [...list].sort((left, right) => {
    const pinDelta = Number(Boolean(right.is_pinned)) - Number(Boolean(left.is_pinned));
    if (pinDelta !== 0) {
      return pinDelta;
    }

    return new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime();
  });
}

function upsertSession(list, session) {
  if (!session) {
    return sortSessions(list);
  }

  const deduped = list.filter((item) => item.id !== session.id);
  return sortSessions([session, ...deduped]);
}

function getSessionDocuments(session) {
  if (!session) {
    return [];
  }

  const documents = Array.isArray(session.documents) ? session.documents : [];
  if (documents.length) {
    return documents;
  }

  return session.document ? [session.document] : [];
}

function getActiveSessionDocument(session) {
  const documents = getSessionDocuments(session);
  return documents.find((document) => document.is_active) || session?.document || null;
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
    .replace(/<\s*(strong|b)\s*>/gi, "**")
    .replace(/<\s*\/\s*(strong|b)\s*>/gi, "**")
    .replace(/<\s*(em|i)\s*>/gi, "*")
    .replace(/<\s*\/\s*(em|i)\s*>/gi, "*")
    .replace(/<\s*u\s*>/gi, "++")
    .replace(/<\s*\/\s*u\s*>/gi, "++")
    .replace(/<\s*code\s*>/gi, "`")
    .replace(/<\s*\/\s*code\s*>/gi, "`")
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

function isMarkdownTableSeparator(line) {
  return /^\s*\|?(?:\s*:?-{3,}:?\s*\|)+(?:\s*:?-{3,}:?\s*)\|?\s*$/.test(String(line || ""));
}

function isMarkdownTableHeader(line) {
  const trimmed = String(line || "").trim();
  return trimmed.includes("|") && parseMarkdownTableRow(trimmed).length >= 2;
}

function parseMarkdownTableRow(line) {
  const trimmed = String(line || "").trim();
  const normalized = trimmed.replace(/^\|/, "").replace(/\|$/, "");
  return normalized.split("|").map((cell) => sanitizeAssistantText(cell.trim()));
}

function parseMarkdownTableBlock(lines) {
  const headers = parseMarkdownTableRow(lines[0] || "");
  const rows = lines
    .slice(2)
    .map((line) => parseMarkdownTableRow(line))
    .filter((cells) => cells.some(Boolean));

  return {
    type: "table",
    headers,
    rows,
  };
}

function isLikelyMathLine(line) {
  const trimmed = String(line || "").trim();
  if (!trimmed) {
    return false;
  }

  return (
    /^\\\[|^\\\]|^\$\$/.test(trimmed)
    || /^\\(begin|end|times|cdot|frac|sqrt|sum|int|left|right|alpha|beta|gamma|theta|pi|sin|cos|tan|log|ln|leq|geq|neq|to|rightarrow|infty|quad|qquad|text)\b/.test(trimmed)
    || /\\times|\\cdot|\\frac|\\sqrt|\\sum|\\int|\\left|\\right/.test(trimmed)
    || /[&^_]/.test(trimmed)
    || /\\\\\s*$/.test(trimmed)
    || /^[=\-+*/()[\]{}0-9.,\s]+$/.test(trimmed)
  );
}

function unwrapMathBlock(value) {
  let math = String(value || "").trim();

  if (math.startsWith("$$") && math.endsWith("$$")) {
    math = math.slice(2, -2).trim();
  } else if (math.startsWith("\\[") && math.endsWith("\\]")) {
    math = math.slice(2, -2).trim();
  } else {
    math = math
      .replace(/^\\\[\s*\n?/, "")
      .replace(/\n?\s*\\\]$/, "")
      .replace(/^\$\$\s*\n?/, "")
      .replace(/\n?\s*\$\$$/, "")
      .trim();
  }

  return math;
}

function findNextDisplayMathSegment(value) {
  const source = String(value || "");
  if (!source) {
    return null;
  }

  const patterns = [
    { type: "bracket", regex: /\\\[[\s\S]*?\\\]/g },
    { type: "dollar", regex: /\$\$[\s\S]*?\$\$/g },
    { type: "environment", regex: /\\begin\{([a-z*]+)\}[\s\S]*?\\end\{\1\}/g },
  ];

  let earliest = null;
  for (const pattern of patterns) {
    pattern.regex.lastIndex = 0;
    const match = pattern.regex.exec(source);
    if (!match) {
      continue;
    }

    if (!earliest || match.index < earliest.index) {
      earliest = {
        index: match.index,
        raw: match[0],
      };
    }
  }

  return earliest;
}

function findNextCodeFenceSegment(value) {
  const source = String(value || "");
  const match = /```([\w.+-]*)\n?([\s\S]*?)```/g.exec(source);
  if (!match) {
    return null;
  }

  return {
    index: match.index,
    raw: match[0],
    language: (match[1] || "").trim(),
    content: match[2].replace(/^\n+|\n+$/g, ""),
  };
}

function findNextSpecialSegment(value) {
  const codeSegment = findNextCodeFenceSegment(value);
  const mathSegment = findNextDisplayMathSegment(value);

  if (codeSegment && (!mathSegment || codeSegment.index <= mathSegment.index)) {
    return {
      type: "code",
      ...codeSegment,
    };
  }

  if (mathSegment) {
    return {
      type: "math",
      ...mathSegment,
    };
  }

  return null;
}

function parseTextOrCodeBlock(block) {
  const trimmedBlock = block.trim();
  if (/^\$\$[\s\S]+\$\$$/.test(trimmedBlock)) {
    return [{
      type: "math",
      display: true,
      content: trimmedBlock.slice(2, -2).trim(),
    }];
  }

  if (/^\\\[[\s\S]+\\\]$/.test(trimmedBlock)) {
    return [{
      type: "math",
      display: true,
      content: trimmedBlock.slice(2, -2).trim(),
    }];
  }

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
    const mixedSegments = [];
    let remaining = block;
    let displayMath = findNextDisplayMathSegment(remaining);

    while (displayMath) {
      const prefix = remaining.slice(0, displayMath.index).trim();
      if (prefix) {
        mixedSegments.push(...parseLooseAssistantBlocks(prefix));
      }

      const expression = unwrapMathBlock(displayMath.raw);
      if (expression) {
        mixedSegments.push({
          type: "math",
          display: true,
          content: expression,
        });
      }

      remaining = remaining.slice(displayMath.index + displayMath.raw.length).trim();
      displayMath = findNextDisplayMathSegment(remaining);
    }

    if (mixedSegments.length) {
      if (remaining) {
        mixedSegments.push(...parseLooseAssistantBlocks(remaining));
      }
      return mixedSegments;
    }

    const lines = block.split("\n");
    const segments = [];
    let buffer = [];

    function flushBuffer() {
      const buffered = buffer.join("\n").trim();
      buffer = [];
      if (!buffered) {
        return;
      }
      segments.push(...parseTextOrCodeBlock(buffered));
    }

    for (let index = 0; index < lines.length; index += 1) {
      const trimmedLine = lines[index].trim();

      if (
        trimmedLine.startsWith("\\[")
        || trimmedLine.startsWith("$$")
        || trimmedLine.startsWith("\\begin{")
      ) {
        flushBuffer();
        const mathLines = [lines[index]];

        while (index + 1 < lines.length && isLikelyMathLine(lines[index + 1])) {
          index += 1;
          mathLines.push(lines[index]);
        }

        const expression = unwrapMathBlock(mathLines.join("\n"));
        if (expression) {
          segments.push({
            type: "math",
            display: true,
            content: expression,
          });
        }
        continue;
      }

      if (
        index + 1 < lines.length
        && isMarkdownTableHeader(lines[index])
        && isMarkdownTableSeparator(lines[index + 1])
      ) {
        flushBuffer();
        const tableLines = [lines[index], lines[index + 1]];
        index += 2;
        while (index < lines.length && lines[index].includes("|")) {
          tableLines.push(lines[index]);
          index += 1;
        }
        index -= 1;
        segments.push(parseMarkdownTableBlock(tableLines));
        continue;
      }

      buffer.push(lines[index]);
    }

    flushBuffer();
    return segments;
  });
}

function parseAssistantMessage(value) {
  const source = normalizeAssistantSource(value);
  const segments = [];
  let remaining = source;
  let specialSegment = findNextSpecialSegment(remaining);

  while (specialSegment) {
    const before = remaining.slice(0, specialSegment.index);
    if (before.trim()) {
      segments.push(...parseLooseAssistantBlocks(before));
    }

    if (specialSegment.type === "code" && specialSegment.content) {
      segments.push({
        type: "code",
        language: specialSegment.language,
        content: specialSegment.content,
      });
    }

    if (specialSegment.type === "math") {
      const expression = unwrapMathBlock(specialSegment.raw);
      if (expression) {
        segments.push({
          type: "math",
          display: true,
          content: expression,
        });
      }
    }

    remaining = remaining.slice(specialSegment.index + specialSegment.raw.length);
    specialSegment = findNextSpecialSegment(remaining);
  }

  if (remaining.trim()) {
    segments.push(...parseLooseAssistantBlocks(remaining));
  }

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

function normalizeCodeLanguage(language) {
  const value = String(language || "").trim().toLowerCase();
  if (!value) {
    return "";
  }

  const aliases = {
    html: "xml",
    vue: "xml",
    jsx: "javascript",
    tsx: "typescript",
    py: "python",
    js: "javascript",
    ts: "typescript",
    yml: "yaml",
    shell: "bash",
    sh: "bash",
  };

  return aliases[value] || value;
}

function renderKatexMarkup(expression, displayMode = false) {
  const katex = window.katex;
  if (!katex?.renderToString || !expression) {
    return "";
  }

  try {
    return katex.renderToString(expression, {
      throwOnError: false,
      displayMode,
      strict: "ignore",
    });
  } catch {
    return "";
  }
}

function MathBlock({ expression, display = false }) {
  const markup = useMemo(() => renderKatexMarkup(expression, display), [expression, display]);
  const fallback = display ? `$$${expression}$$` : `$${expression}$`;

  if (!markup) {
    return display
      ? <div className="message-math-block">{fallback}</div>
      : <span className="message-inline-math">{fallback}</span>;
  }

  return display ? (
    <div
      className="message-math-block"
      dangerouslySetInnerHTML={{ __html: markup }}
    />
  ) : (
    <span
      className="message-inline-math"
      dangerouslySetInnerHTML={{ __html: markup }}
    />
  );
}

function CodeBlock({ language, code }) {
  const [copied, setCopied] = useState(false);
  const codeRef = useRef(null);
  const resolvedLanguage = useMemo(() => normalizeCodeLanguage(language), [language]);

  useEffect(() => {
    if (!copied) {
      return undefined;
    }

    const timer = window.setTimeout(() => setCopied(false), 1800);
    return () => window.clearTimeout(timer);
  }, [copied]);

  useEffect(() => {
    if (!codeRef.current) {
      return;
    }

    codeRef.current.removeAttribute("data-highlighted");
    codeRef.current.className = resolvedLanguage ? `language-${resolvedLanguage}` : "";

    if (resolvedLanguage && hljs.getLanguage(resolvedLanguage)) {
      hljs.highlightElement(codeRef.current);
      return;
    }

    hljs.highlightElement(codeRef.current);
  }, [code, resolvedLanguage]);

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
        <span className="message-code-language">{resolvedLanguage || language || "Code"}</span>
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
        <code ref={codeRef}>{code}</code>
      </pre>
    </div>
  );
}

function renderInlineRichText(text) {
  const source = String(text || "");
  const tokens = [];
  const pattern = /(\\\((?:\\.|[^\\])+?\\\)|\$(?:\\.|[^$\n])+\$|\*\*[^*]+?\*\*|__[^_]+?__|\*[^*\n]+?\*|_[^_\n]+?_|\+\+[^+\n]+?\+\+|`[^`\n]+?`)/g;
  let lastIndex = 0;
  let match = pattern.exec(source);

  while (match) {
    if (match.index > lastIndex) {
      tokens.push(source.slice(lastIndex, match.index));
    }

    const token = match[0];
    if (token.startsWith("\\(") && token.endsWith("\\)")) {
      tokens.push(<MathBlock key={`math-${match.index}`} expression={token.slice(2, -2).trim()} />);
    } else if (token.startsWith("$") && token.endsWith("$")) {
      tokens.push(<MathBlock key={`math-${match.index}`} expression={token.slice(1, -1).trim()} />);
    } else if ((token.startsWith("**") && token.endsWith("**")) || (token.startsWith("__") && token.endsWith("__"))) {
      tokens.push(<strong key={`strong-${match.index}`}>{token.slice(2, -2)}</strong>);
    } else if ((token.startsWith("*") && token.endsWith("*")) || (token.startsWith("_") && token.endsWith("_"))) {
      tokens.push(<em key={`em-${match.index}`}>{token.slice(1, -1)}</em>);
    } else if (token.startsWith("++") && token.endsWith("++")) {
      tokens.push(<u key={`u-${match.index}`}>{token.slice(2, -2)}</u>);
    } else if (token.startsWith("`") && token.endsWith("`")) {
      tokens.push(<code className="message-inline-code" key={`code-${match.index}`}>{token.slice(1, -1)}</code>);
    } else {
      tokens.push(token);
    }

    lastIndex = pattern.lastIndex;
    match = pattern.exec(source);
  }

  if (lastIndex < source.length) {
    tokens.push(source.slice(lastIndex));
  }

  return tokens;
}

function RichTextBlock({ text }) {
  const lines = String(text || "").split("\n");

  return (
    <div className="message-richtext">
      {lines.map((line, index) => (
        <Fragment key={`line-${index}`}>
          {renderInlineRichText(line)}
          {index < lines.length - 1 ? <br /> : null}
        </Fragment>
      ))}
    </div>
  );
}

function TableBlock({ headers, rows }) {
  return (
    <div className="message-table-wrap">
      <table className="message-table">
        <thead>
          <tr>
            {headers.map((header, index) => (
              <th key={`head-${index}`}><RichTextBlock text={header} /></th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={`row-${rowIndex}`}>
              {headers.map((_, cellIndex) => (
                <td key={`cell-${rowIndex}-${cellIndex}`}><RichTextBlock text={row[cellIndex] || ""} /></td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
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
        ) : segment.type === "table" ? (
          <TableBlock
            key={`table-${index}`}
            headers={segment.headers}
            rows={segment.rows}
          />
        ) : segment.type === "math" ? (
          <MathBlock
            key={`math-block-${index}`}
            expression={segment.content}
            display={segment.display}
          />
        ) : (
          <div className="message-body" key={`text-${index}`}>
            <RichTextBlock text={segment.content} />
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

function SidebarNav({ currentPage, onOpenChats, onOpenProfile, onOpenLearn }) {
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
      <button
        className={`nav-chip ${currentPage === "learn" ? "active" : ""}`}
        type="button"
        onClick={onOpenLearn}
      >
        <i className="bi bi-mortarboard" />
        Learn
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
  searchValue,
  busy,
  pinnedCount,
  pinningSessionId,
  onNewChat,
  onClose,
  onOpenChats,
  onOpenProfile,
  onOpenLearn,
  onSearchChange,
  onSelect,
  onTogglePin,
  onDelete,
}) {
  const filteredSessions = useMemo(() => {
    const query = searchValue.trim().toLowerCase();
    if (!query) {
      return sessions;
    }

    return sessions.filter((session) =>
      [session.title, session.model, session.preview]
        .filter(Boolean)
        .some((value) => value.toLowerCase().includes(query)),
    );
  }, [searchValue, sessions]);

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
        <SidebarNav
          currentPage={currentPage}
          onOpenChats={onOpenChats}
          onOpenProfile={onOpenProfile}
          onOpenLearn={onOpenLearn}
        />
        <label className="sidebar-search">
          <i className="bi bi-search" />
          <input
            type="search"
            value={searchValue}
            onChange={onSearchChange}
            placeholder="Search chats"
            aria-label="Search chats"
          />
        </label>
        <button className="primary-button full-width" type="button" onClick={onNewChat} disabled={busy}>
          <i className="bi bi-plus-lg" />
          New chat
        </button>
      </div>

      <div className="sidebar-block sidebar-sessions">
        <div className="section-heading">
          <span>Recent chats</span>
          <span>{filteredSessions.length}</span>
        </div>
        {filteredSessions.length ? (
          filteredSessions.map((session) => {
            const pinLimitReached = !session.is_pinned && pinnedCount >= 3;
            const pinTitle = pinLimitReached
              ? "Only 3 chats can be pinned"
              : session.is_pinned
                ? `Unpin ${session.title}`
                : `Pin ${session.title}`;

            return (
              <article
                key={session.id}
                className={`session-card ${session.id === activeSessionId ? "active" : ""}`}
              >
                <button
                  className="session-main"
                  type="button"
                  onClick={() => onSelect(session.id)}
                  disabled={busy}
                >
                  <span className="session-title">{session.title}</span>
                  <span className="session-meta">
                    {session.model} • {formatTimestamp(session.updated_at)}
                  </span>
                  {getActiveSessionDocument(session) ? (
                    <span className="session-tag">
                      <i className="bi bi-file-earmark-pdf" />
                      {getActiveSessionDocument(session).name}
                    </span>
                  ) : null}
                  <span className="session-preview">{session.preview || "No messages yet."}</span>
                </button>
                <div className="session-actions">
                  <button
                    className={`session-pin icon-button ${session.is_pinned ? "active" : ""}`}
                    type="button"
                    onClick={() => onTogglePin(session)}
                    aria-label={pinTitle}
                    title={pinTitle}
                    disabled={busy || pinningSessionId === session.id || pinLimitReached}
                  >
                    <i className={`bi ${session.is_pinned ? "bi-pin-angle-fill" : "bi-pin-angle"}`} />
                  </button>
                  <button
                    className="session-delete icon-button"
                    type="button"
                    onClick={() => onDelete(session.id)}
                    aria-label={`Delete ${session.title}`}
                    title={`Delete ${session.title}`}
                    disabled={busy}
                  >
                    <i className="bi bi-trash3" />
                  </button>
                </div>
              </article>
            );
          })
        ) : (
          <div className="empty-card">
            <p>
              {searchValue.trim()
                ? "No chats match this search yet."
                : "Your private chat history will appear here after the first message."}
            </p>
          </div>
        )}
      </div>
    </aside>
  );
}

function UsageModelChart({ data, theme }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    if (!canvasRef.current || !window.Chart || !data.length) {
      return undefined;
    }

    const chart = new window.Chart(canvasRef.current, {
      type: "bar",
      data: {
        labels: data.map((item) => item.model),
        datasets: [
          {
            label: "Input",
            data: data.map((item) => item.total_input_tokens),
            backgroundColor: theme === "dark" ? "rgba(125, 211, 176, 0.72)" : "rgba(23, 89, 74, 0.72)",
            borderRadius: 12,
            borderSkipped: false,
          },
          {
            label: "Output",
            data: data.map((item) => item.total_output_tokens),
            backgroundColor: theme === "dark" ? "rgba(127, 215, 255, 0.78)" : "rgba(59, 130, 246, 0.72)",
            borderRadius: 12,
            borderSkipped: false,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            labels: {
              color: theme === "dark" ? "#dbe7f4" : "#334155",
              usePointStyle: true,
              boxWidth: 10,
            },
          },
        },
        scales: {
          x: {
            ticks: {
              color: theme === "dark" ? "#9fb0c3" : "#64748b",
            },
            grid: {
              display: false,
            },
          },
          y: {
            ticks: {
              color: theme === "dark" ? "#9fb0c3" : "#64748b",
            },
            grid: {
              color: theme === "dark" ? "rgba(148, 163, 184, 0.14)" : "rgba(148, 163, 184, 0.16)",
            },
          },
        },
      },
    });

    return () => chart.destroy();
  }, [data, theme]);

  if (!data.length) {
    return <p className="small-note">Model usage will appear here once you have conversations.</p>;
  }

  return (
    <div className="usage-chart-shell">
      <canvas ref={canvasRef} />
    </div>
  );
}

function UsageCard({ usage, usageByModel, theme }) {
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
      <div className="usage-model-panel">
        <div className="section-heading">
          <span><i className="bi bi-pie-chart" /> Model usage</span>
          <span>{usageByModel.length}</span>
        </div>
        <p className="small-note">Each bar shows per-model token usage for this private account.</p>
        <UsageModelChart data={usageByModel} theme={theme} />
      </div>
    </section>
  );
}

function ProfileStatsDashboard({ usage }) {
  const dashboard = usage?.dashboard || {};
  const cards = [
    {
      label: "Total messages",
      value: String(dashboard.total_messages || 0),
      note: "Every private user prompt and AI reply saved in this account.",
      icon: "bi-chat-square-text",
    },
    {
      label: "Favorite model",
      value: dashboard.favorite_model || "No activity yet",
      note:
        dashboard.favorite_model_messages > 0
          ? `${dashboard.favorite_model_messages} messages with this model so far.`
          : "Your most-used model will appear here after activity.",
      icon: "bi-cpu",
    },
    {
      label: "Most active time",
      value: dashboard.most_active_time || "No activity yet",
      note:
        dashboard.most_active_time_messages > 0
          ? `${dashboard.most_active_time_messages} messages usually land in this time window.`
          : "A peak activity window appears after your chats build up.",
      icon: "bi-clock-history",
    },
  ];

  return (
    <section className="profile-stats-grid">
      {cards.map((card) => (
        <article key={card.label} className="profile-card profile-stat-card">
          <span className="overview-label"><i className={`bi ${card.icon}`} /> {card.label}</span>
          <strong className="overview-value profile-value profile-stat-value">{card.value}</strong>
          <p className="small-note">{card.note}</p>
        </article>
      ))}
    </section>
  );
}

function ProfilePage({ currentUser, usage, usageByModel, sessions, theme }) {
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

      <ProfileStatsDashboard usage={usage} />

      <UsageCard usage={usage} usageByModel={usageByModel} theme={theme} />
    </div>
  );
}

function upsertQuizHistory(list, quiz) {
  const deduped = list.filter((item) => item.id !== quiz.id);
  return [quiz, ...deduped].sort(
    (left, right) => new Date(right.created_at).getTime() - new Date(left.created_at).getTime(),
  );
}

function QuizModeCard({
  models,
  topic,
  model,
  questionCount,
  loading,
  activeQuiz,
  quizHistory,
  onTopicChange,
  onModelChange,
  onQuestionCountChange,
  onStartQuiz,
  onOpenQuiz,
}) {
  const isQuizCompleted = Boolean(activeQuiz?.is_completed);
  const activeQuizLabel = !activeQuiz
    ? "MCQ"
    : isQuizCompleted
      ? `${activeQuiz.correct_answers}/${activeQuiz.total_questions}`
      : "Continue";

  return (
    <section className="learn-card">
      <div className="section-heading">
        <span><i className="bi bi-patch-question" /> Quiz mode</span>
        <span>{activeQuizLabel}</span>
      </div>
      <p className="small-note">
        Ask the AI to test you on a topic with multiple-choice questions and tracked scoring.
      </p>

      <form className="learn-form" onSubmit={onStartQuiz}>
        <label>
          <span>Topic</span>
          <input
            type="text"
            value={topic}
            onChange={onTopicChange}
            placeholder="Django ORM"
            required
          />
        </label>
        <div className="learn-form-row">
          <label className="learn-form-field">
            <span>Model</span>
            <select value={model} onChange={onModelChange}>
              {models.map((item) => (
                <option key={item.key} value={item.key}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label className="learn-form-field">
            <span>Questions</span>
            <select value={questionCount} onChange={onQuestionCountChange}>
              {[5, 7, 10].map((count) => (
                <option key={count} value={String(count)}>
                  {count}
                </option>
              ))}
            </select>
          </label>
        </div>
        <button className="primary-button" type="submit" disabled={loading}>
          <i className={`bi ${loading ? "bi-arrow-repeat" : "bi-stars"}`} />
          {loading ? "Building quiz..." : "Generate quiz"}
        </button>
      </form>

      {activeQuiz ? (
        <div className="quiz-stage">
          <div className="quiz-summary-strip">
            <article>
              <span>Topic</span>
              <strong>{activeQuiz.topic}</strong>
            </article>
            <article>
              <span>Progress</span>
              <strong>{activeQuiz.answered_questions}/{activeQuiz.total_questions}</strong>
            </article>
            <article>
              <span>{isQuizCompleted ? "Score" : "Status"}</span>
              <strong>{isQuizCompleted ? `${activeQuiz.score_percent}%` : "Continue"}</strong>
            </article>
          </div>
          {!isQuizCompleted ? (
            <button className="primary-button quiz-launch-button" type="button" onClick={() => onOpenQuiz(activeQuiz)}>
              <i className="bi bi-play-circle" />
              {activeQuiz.answered_questions > 0 ? "Continue quiz" : "Start quiz"}
            </button>
          ) : (
            <div className="quiz-feedback is-finished quiz-result-card">
              <strong>Quiz completed</strong>
              <p>
                You finished this quiz with {activeQuiz.correct_answers} correct answers out of{" "}
                {activeQuiz.total_questions}.
              </p>
              <button className="secondary-button" type="button" onClick={() => onOpenQuiz(activeQuiz)}>
                <i className="bi bi-journal-text" />
                Review answers
              </button>
            </div>
          )}
        </div>
      ) : null}

      <div className="learn-history">
        <div className="section-heading">
          <span><i className="bi bi-clock-history" /> Recent quizzes</span>
          <span>{quizHistory.length}</span>
        </div>
        {quizHistory.length ? (
          <div className="quiz-history-list">
            {quizHistory.map((quiz) => (
              <article key={quiz.id} className="quiz-history-item">
                <div>
                  <strong>{quiz.topic}</strong>
                  <span>{quiz.model} • {formatTimestamp(quiz.created_at)}</span>
                </div>
                <div className="quiz-history-score">
                  <strong>{quiz.is_completed ? `${quiz.score_percent}%` : "Continue"}</strong>
                  <span>{quiz.is_completed ? `${quiz.correct_answers}/${quiz.total_questions}` : `${quiz.answered_questions}/${quiz.total_questions}`}</span>
                </div>
                <button className="secondary-button quiz-history-action" type="button" onClick={() => onOpenQuiz(quiz)}>
                  <i className={`bi ${quiz.is_completed ? "bi-journal-check" : "bi-play-circle"}`} />
                  {quiz.is_completed ? "Review" : "Continue"}
                </button>
              </article>
            ))}
          </div>
        ) : (
          <p className="small-note">Quiz history will show up here after your first attempt.</p>
        )}
      </div>
    </section>
  );
}

function QuizModal({
  quiz,
  focusQuestionId,
  answeringQuestionId,
  open,
  onClose,
  onAnswer,
  onContinue,
  onPrevious,
}) {
  if (!open || !quiz) {
    return null;
  }

  const questions = quiz.questions || [];
  const currentQuestion = questions.find((item) => item.id === focusQuestionId)
    || questions.find((item) => !item.selected_option)
    || questions[questions.length - 1]
    || null;
  const nextUnansweredQuestion = questions.find((item) => !item.selected_option) || null;
  const showingAnsweredQuestion = Boolean(currentQuestion?.selected_option);

  return (
    <>
      <button
        className="quiz-modal-backdrop"
        type="button"
        onClick={onClose}
        aria-label="Close quiz"
      />
      <div className="quiz-modal" role="dialog" aria-modal="true" aria-label="Quiz mode">
        <div className="quiz-modal-head">
          <div className="section-heading">
            <span><i className="bi bi-patch-question" /> {quiz.topic}</span>
            <span>{quiz.answered_questions}/{quiz.total_questions}</span>
          </div>
          <button
            className="secondary-button icon-button"
            type="button"
            onClick={onClose}
            aria-label="Close quiz"
            title="Close quiz"
          >
            <i className="bi bi-x-lg" />
          </button>
        </div>

        <div className="quiz-summary-strip">
          <article>
            <span>Topic</span>
            <strong>{quiz.topic}</strong>
          </article>
          <article>
            <span>Progress</span>
            <strong>{quiz.answered_questions}/{quiz.total_questions}</strong>
          </article>
          <article>
            <span>{quiz.is_completed ? "Score" : "Status"}</span>
            <strong>{quiz.is_completed ? `${quiz.score_percent}%` : "In progress"}</strong>
          </article>
        </div>

        {currentQuestion ? (
          <div className="quiz-question-card quiz-question-card-modal">
            <span className="overview-label">Question {currentQuestion.sort_order}</span>
            <h3>{currentQuestion.question_text}</h3>
            <div className="quiz-options">
              {Object.entries(currentQuestion.options || {}).map(([key, label]) => {
                const isSelected = currentQuestion.selected_option === key;
                const isCorrect = currentQuestion.correct_option === key;
                return (
                  <button
                    key={key}
                    className={`quiz-option ${isSelected ? "is-selected" : ""} ${showingAnsweredQuestion && isCorrect ? "is-correct" : ""} ${showingAnsweredQuestion && isSelected && !isCorrect ? "is-wrong" : ""}`}
                    type="button"
                    disabled={Boolean(answeringQuestionId || currentQuestion.selected_option || quiz.is_completed)}
                    onClick={() => onAnswer(currentQuestion, key)}
                  >
                    <span>{key}</span>
                    <strong>{label}</strong>
                  </button>
                );
              })}
            </div>
            {showingAnsweredQuestion ? (
              <div className={`quiz-feedback ${currentQuestion.is_correct ? "is-correct" : "is-wrong"}`}>
                <strong>
                  {currentQuestion.is_correct
                    ? "Correct answer"
                    : `Correct answer: ${currentQuestion.correct_option}`}
                </strong>
                <p>{currentQuestion.explanation}</p>
                <div className="quiz-feedback-actions">
                  {currentQuestion.sort_order > 1 ? (
                    <button className="secondary-button" type="button" onClick={onPrevious}>
                      <i className="bi bi-arrow-left" />
                      Previous
                    </button>
                  ) : null}
                  {((quiz.is_completed && currentQuestion.sort_order < questions.length)
                    || (!quiz.is_completed && nextUnansweredQuestion && nextUnansweredQuestion.id !== currentQuestion.id)) ? (
                    <button className="secondary-button" type="button" onClick={onContinue}>
                      <i className="bi bi-arrow-right" />
                      Next question
                    </button>
                  ) : null}
                </div>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </>
  );
}

function LearningPathCard({
  models,
  form,
  loading,
  result,
  onFormChange,
  onSubmit,
}) {
  return (
    <section className="learn-card">
      <div className="section-heading">
        <span><i className="bi bi-signpost-split" /> Learning path</span>
        <span>{result?.milestones?.length || "Roadmap"}</span>
      </div>
      <p className="small-note">
        Turn a learning goal into a structured roadmap with milestones, focus areas, and deliverables.
      </p>

      <form className="learn-form" onSubmit={onSubmit}>
        <label>
          <span>Goal</span>
          <input
            type="text"
            name="goal"
            value={form.goal}
            onChange={onFormChange}
            placeholder="I want to learn machine learning"
            required
          />
        </label>
        <div className="learn-form-row">
          <label className="learn-form-field">
            <span>Level</span>
            <input
              type="text"
              name="experience_level"
              value={form.experience_level}
              onChange={onFormChange}
              placeholder="Beginner"
            />
          </label>
          <label className="learn-form-field">
            <span>Hours / week</span>
            <input
              type="text"
              name="weekly_hours"
              value={form.weekly_hours}
              onChange={onFormChange}
              placeholder="8"
            />
          </label>
        </div>
        <div className="learn-form-row">
          <label className="learn-form-field">
            <span>Timeline</span>
            <input
              type="text"
              name="timeline"
              value={form.timeline}
              onChange={onFormChange}
              placeholder="3 months"
            />
          </label>
          <label className="learn-form-field">
            <span>Model</span>
            <select name="model" value={form.model} onChange={onFormChange}>
              {models.map((item) => (
                <option key={item.key} value={item.key}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <button className="primary-button" type="submit" disabled={loading}>
          <i className={`bi ${loading ? "bi-arrow-repeat" : "bi-diagram-3"}`} />
          {loading ? "Generating path..." : "Generate roadmap"}
        </button>
      </form>

      {result ? (
        <div className="roadmap-result">
          <div className="roadmap-summary">
            <span className="overview-label">Roadmap</span>
            <h3>{result.title}</h3>
            <p>{result.summary}</p>
          </div>

          {result.first_steps?.length ? (
            <div className="roadmap-first-steps">
              <div className="section-heading">
                <span><i className="bi bi-lightning-charge" /> First steps</span>
                <span>{result.first_steps.length}</span>
              </div>
              <ul className="roadmap-step-list">
                {result.first_steps.map((step) => (
                  <li key={step}>{step}</li>
                ))}
              </ul>
            </div>
          ) : null}

          <div className="roadmap-milestones">
            {result.milestones?.map((milestone, index) => (
              <article key={`${milestone.title}-${index}`} className="roadmap-milestone">
                <span className="overview-label">Milestone {index + 1}</span>
                <h4>{milestone.title}</h4>
                <p><strong>Duration:</strong> {milestone.duration}</p>
                <p><strong>Focus:</strong> {milestone.focus}</p>
                <p><strong>Deliverable:</strong> {milestone.deliverable}</p>
              </article>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}

function LearnPage({
  models,
  quizTopic,
  quizModel,
  quizQuestionCount,
  quizLoading,
  activeQuiz,
  quizHistory,
  quizFocusQuestionId,
  answeringQuizQuestionId,
  quizModalOpen,
  learningPathForm,
  learningPathLoading,
  learningPath,
  onQuizTopicChange,
  onQuizModelChange,
  onQuizQuestionCountChange,
  onStartQuiz,
  onOpenQuiz,
  onCloseQuiz,
  onAnswerQuizQuestion,
  onContinueQuiz,
  onPreviousQuiz,
  onLearningPathFormChange,
  onGenerateLearningPath,
}) {
  return (
    <div className="learn-page">
      <div className="learn-grid">
        <QuizModeCard
          models={models}
          topic={quizTopic}
          model={quizModel}
          questionCount={quizQuestionCount}
          loading={quizLoading}
          activeQuiz={activeQuiz}
          quizHistory={quizHistory}
          onTopicChange={onQuizTopicChange}
          onModelChange={onQuizModelChange}
          onQuestionCountChange={onQuizQuestionCountChange}
          onStartQuiz={onStartQuiz}
          onOpenQuiz={onOpenQuiz}
        />
        <LearningPathCard
          models={models}
          form={learningPathForm}
          loading={learningPathLoading}
          result={learningPath}
          onFormChange={onLearningPathFormChange}
          onSubmit={onGenerateLearningPath}
        />
      </div>

      <QuizModal
        quiz={activeQuiz}
        focusQuestionId={quizFocusQuestionId}
        answeringQuestionId={answeringQuizQuestionId}
        open={quizModalOpen}
        onClose={onCloseQuiz}
        onAnswer={onAnswerQuizQuestion}
        onContinue={onContinueQuiz}
        onPrevious={onPreviousQuiz}
      />
    </div>
  );
}

function DocumentPanel({
  activeSession,
  selectedModel,
  models,
  uploading,
  selectingDocumentId,
  open,
  onClose,
  onUpload,
  onSelectDocument,
}) {
  const fileInputRef = useRef(null);
  const activeModelKey = activeSession?.model || selectedModel;
  const activeModel = models.find((item) => item.key === activeModelKey) || null;
  const canUploadToCurrent = !activeSession || Boolean(activeModel?.supports_documents);
  const documents = getSessionDocuments(activeSession);
  const activeDocument = getActiveSessionDocument(activeSession);

  return (
    <aside className={`document-panel ${open ? "is-open" : ""}`}>
      <div className="document-panel-copy">
        <div className="document-panel-head">
          <div className="section-heading">
            <span><i className="bi bi-file-earmark-pdf" /> Document chat</span>
            <span>{documents.length ? `${documents.length} saved` : "PDF only"}</span>
          </div>
          <button
            className="secondary-button icon-button document-panel-close"
            type="button"
            onClick={onClose}
            aria-label="Close document panel"
            title="Close document panel"
          >
            <i className="bi bi-x-lg" />
          </button>
        </div>
        {activeDocument ? (
          <div className="document-status">
            <strong>{activeDocument.name}</strong>
            <span>
              {formatTokenCount(activeDocument.extracted_characters)} chars extracted • model locked to {activeSession.model}
            </span>
          </div>
        ) : (
          <div className="document-status muted">
            <strong>{activeModel?.label || "Choose a model"}</strong>
            <span>
              {activeModel?.supports_documents
                ? "This model can be used for PDF chat."
                : "Choose a document-capable model before uploading a PDF."}
            </span>
          </div>
        )}

        {documents.length ? (
          <div className="document-library">
            <div className="section-heading">
              <span>Saved PDFs</span>
              <span>{documents.length}</span>
            </div>
            <div className="document-list">
              {documents.map((document) => (
                <button
                  key={document.id}
                  className={`document-item ${document.is_active ? "is-active" : ""}`}
                  type="button"
                  onClick={() => onSelectDocument(document.id)}
                  disabled={uploading || selectingDocumentId === document.id}
                >
                  <span className="document-item-main">
                    <strong>{document.name}</strong>
                    <span>
                      {formatTokenCount(document.extracted_characters)} chars extracted • {formatTimestamp(document.uploaded_at)}
                    </span>
                  </span>
                  <span className="document-item-side">
                    {selectingDocumentId === document.id ? (
                      <i className="bi bi-arrow-repeat" />
                    ) : document.is_active ? (
                      <span className="document-item-badge">Selected</span>
                    ) : (
                      <span className="document-item-link">Use</span>
                    )}
                  </span>
                </button>
              ))}
            </div>
          </div>
        ) : null}
      </div>

      <div className="document-panel-actions">
        <input
          ref={fileInputRef}
          className="document-input"
          type="file"
          accept="application/pdf,.pdf"
          onChange={onUpload}
          disabled={uploading || !canUploadToCurrent}
        />
        <button
          className="secondary-button"
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={uploading || !canUploadToCurrent}
        >
          <i className={`bi ${uploading ? "bi-arrow-repeat" : "bi-upload"}`} />
          {uploading ? "Uploading..." : documents.length ? "Add PDF" : "Upload PDF"}
        </button>
      </div>
    </aside>
  );
}

function ChatComposer({
  draft,
  model,
  models,
  isLocked,
  sending,
  stoppingGeneration,
  documentOpen,
  documentAvailable,
  onDraftChange,
  onModelChange,
  onDraftKeyDown,
  onToggleDocument,
  onSubmit,
  onStop,
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
        <button
          className={`secondary-button composer-icon-button ${documentOpen ? "is-active" : ""}`}
          type="button"
          onClick={onToggleDocument}
          disabled={!documentAvailable}
          title="Open PDF panel"
          aria-label="Open PDF panel"
        >
          <i className="bi bi-file-earmark-pdf" />
        </button>
        <button
          className={`primary-button composer-button ${sending ? "stop-button" : ""}`}
          type={sending ? "button" : "submit"}
          onClick={sending ? onStop : undefined}
          disabled={stoppingGeneration}
        >
          <i
            className={`bi ${
              sending ? (stoppingGeneration ? "bi-hourglass-split" : "bi-stop-circle") : "bi-send"
            }`}
          />
          {sending ? (stoppingGeneration ? "Stopping..." : "Stop") : "Send"}
        </button>
      </div>
    </form>
  );
}

function MessageList({
  activeSessionId,
  branding,
  messages,
  pendingPrompt,
  streamingResponse,
  loadingConversation,
  editingMessageId,
  editingDraft,
  regeneratingMessageId,
  savingEditMessageId,
  readOnly = false,
  sharedOwner = "",
  onEditDraftChange,
  onStartEdit,
  onCancelEdit,
  onSaveEdit,
  onRegenerate,
}) {
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, pendingPrompt, streamingResponse, loadingConversation]);

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
              <div className="message-meta">
                <time>{formatTimestamp(message.created_at)}</time>
                {!readOnly ? (
                  <button
                    className="message-action"
                    type="button"
                    onClick={() => onStartEdit(message)}
                    disabled={Boolean(regeneratingMessageId || savingEditMessageId)}
                  >
                    <i className={`bi ${editingMessageId === message.id ? "bi-pencil-fill" : "bi-pencil"}`} />
                    {editingMessageId === message.id ? "Editing" : "Edit"}
                  </button>
                ) : null}
              </div>
            </header>
            {editingMessageId === message.id ? (
              <div className="message-edit-form">
                <textarea value={editingDraft} onChange={onEditDraftChange} rows={4} />
                <div className="message-edit-actions">
                  <button className="secondary-button" type="button" onClick={onCancelEdit}>
                    Cancel
                  </button>
                  <button
                    className="primary-button"
                    type="button"
                    onClick={() => onSaveEdit(message)}
                    disabled={savingEditMessageId === message.id}
                  >
                    <i className={`bi ${savingEditMessageId === message.id ? "bi-arrow-repeat" : "bi-check2"}`} />
                    {savingEditMessageId === message.id ? "Saving..." : "Save and resend"}
                  </button>
                </div>
              </div>
            ) : (
              <div className="message-body">{message.user_message}</div>
            )}
          </article>
          <article className="message-bubble assistant">
            <header>
              <span>{readOnly ? `${branding.website_name} • shared by ${sharedOwner}` : branding.website_name}</span>
              {!readOnly ? (
                <div className="message-meta">
                  <button
                    className="message-action"
                    type="button"
                    onClick={() => onRegenerate(message)}
                    disabled={Boolean(regeneratingMessageId || savingEditMessageId)}
                  >
                    <i className={`bi ${regeneratingMessageId === message.id ? "bi-arrow-repeat" : "bi-arrow-clockwise"}`} />
                    {regeneratingMessageId === message.id ? "Regenerating..." : "Regenerate"}
                  </button>
                </div>
              ) : null}
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
            {streamingResponse ? (
              <AssistantMessageContent value={streamingResponse} />
            ) : (
              <div className="message-body subtle">Thinking...</div>
            )}
          </article>
        </div>
      ) : null}
      <div ref={bottomRef} />
    </div>
  );
}

function SharedChatPage({ branding, sharePayload, shareNotFound, theme, onThemeToggle }) {
  return (
    <div className="app-shell shared-shell">
      <main className="workspace">
        <header className="workspace-header">
          <div className="workspace-heading">
            <div className="workspace-heading-copy">
              <p className="eyebrow">Shared read-only chat</p>
              <h1>{sharePayload?.session?.title || "Shared conversation"}</h1>
              <p className="workspace-subtitle">
                {shareNotFound
                  ? "This shared link is missing or no longer public."
                  : `Anyone with this link can view the conversation in read-only mode.`}
              </p>
            </div>
          </div>
          <div className="workspace-actions">
            <ThemeToggle theme={theme} onToggle={onThemeToggle} />
            <a className="secondary-button icon-button" href="/" aria-label="Open main app" title="Open main app">
              <i className="bi bi-house" />
            </a>
          </div>
        </header>

        <section className="conversation-panel">
          {shareNotFound ? (
            <div className="message-empty">
              <p className="eyebrow">Unavailable</p>
              <h2>Shared chat not found.</h2>
              <p>The owner may have disabled sharing or removed this conversation.</p>
            </div>
          ) : (
            <MessageList
              activeSessionId={null}
              branding={branding}
              messages={sharePayload?.messages || []}
              pendingPrompt=""
              streamingResponse=""
              loadingConversation={!sharePayload}
              editingMessageId={null}
              editingDraft=""
              regeneratingMessageId={null}
              savingEditMessageId={null}
              readOnly
              sharedOwner={sharePayload?.owner?.username || "owner"}
              onEditDraftChange={() => {}}
              onStartEdit={() => {}}
              onCancelEdit={() => {}}
              onSaveEdit={() => {}}
              onRegenerate={() => {}}
            />
          )}
        </section>
      </main>
    </div>
  );
}

export default function App() {
  const shareToken = useMemo(() => getShareTokenFromPath(), []);
  const isSharedView = Boolean(shareToken);
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
  const [usageByModel, setUsageByModel] = useState([]);
  const [draft, setDraft] = useState("");
  const [sessionSearch, setSessionSearch] = useState("");
  const [selectedModel, setSelectedModel] = useState("");
  const [uploadingDocument, setUploadingDocument] = useState(false);
  const [selectingDocumentId, setSelectingDocumentId] = useState(null);
  const [documentPanelOpen, setDocumentPanelOpen] = useState(false);
  const [mobileActionsOpen, setMobileActionsOpen] = useState(false);
  const [sending, setSending] = useState(false);
  const [stoppingGeneration, setStoppingGeneration] = useState(false);
  const [activeStreamId, setActiveStreamId] = useState("");
  const [streamingResponse, setStreamingResponse] = useState("");
  const [pinningSessionId, setPinningSessionId] = useState(null);
  const [sharingSessionId, setSharingSessionId] = useState(null);
  const [regeneratingMessageId, setRegeneratingMessageId] = useState(null);
  const [editingMessageId, setEditingMessageId] = useState(null);
  const [editingDraft, setEditingDraft] = useState("");
  const [savingEditMessageId, setSavingEditMessageId] = useState(null);
  const [quizTopic, setQuizTopic] = useState("");
  const [quizModel, setQuizModel] = useState("");
  const [quizQuestionCount, setQuizQuestionCount] = useState("5");
  const [quizLoading, setQuizLoading] = useState(false);
  const [quizHistory, setQuizHistory] = useState([]);
  const [activeQuiz, setActiveQuiz] = useState(null);
  const [quizFocusQuestionId, setQuizFocusQuestionId] = useState(null);
  const [answeringQuizQuestionId, setAnsweringQuizQuestionId] = useState(null);
  const [quizModalOpen, setQuizModalOpen] = useState(false);
  const [learningPathForm, setLearningPathForm] = useState({
    goal: "",
    experience_level: "",
    weekly_hours: "",
    timeline: "",
    model: "",
  });
  const [learningPathLoading, setLearningPathLoading] = useState(false);
  const [learningPath, setLearningPath] = useState(null);
  const [loadingConversation, setLoadingConversation] = useState(false);
  const [pendingPrompt, setPendingPrompt] = useState("");
  const [sharedChat, setSharedChat] = useState(null);
  const [shareNotFound, setShareNotFound] = useState(false);
  const [toasts, setToasts] = useState([]);
  const toastIdRef = useRef(0);
  const streamAbortRef = useRef(null);

  const activeSession = useMemo(
    () => sessions.find((session) => session.id === activeSessionId) || null,
    [sessions, activeSessionId],
  );
  const documentCapableModels = useMemo(
    () => models.filter((model) => model.supports_documents),
    [models],
  );
  const pinnedCount = useMemo(
    () => sessions.filter((session) => session.is_pinned).length,
    [sessions],
  );

  function abortStreamRequest() {
    streamAbortRef.current?.abort();
    streamAbortRef.current = null;
  }

  function resetStreamingState() {
    setSending(false);
    setStoppingGeneration(false);
    setActiveStreamId("");
    setPendingPrompt("");
    setStreamingResponse("");
  }

  function clearEditState() {
    setEditingMessageId(null);
    setEditingDraft("");
    setSavingEditMessageId(null);
  }

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

  useEffect(() => () => abortStreamRequest(), []);

  useEffect(() => {
    if (!models.length) {
      return;
    }
    setQuizModel((current) => current || models[0].key);
    setLearningPathForm((current) => (
      current.model ? current : { ...current, model: models[0].key }
    ));
  }, [models]);

  useEffect(() => {
    setMobileActionsOpen(false);
  }, [activeSessionId, currentPage, sidebarOpen, documentPanelOpen]);

  useEffect(() => {
    if (!("serviceWorker" in navigator)) {
      return undefined;
    }

    const registerWorker = async () => {
      try {
        await navigator.serviceWorker.register("/sw.js");
      } catch {
        // Installability support should stay silent if registration fails.
      }
    };

    registerWorker();
    return undefined;
  }, []);

  useEffect(() => {
    syncDocumentBranding(branding);
  }, [branding]);

  useEffect(() => {
    async function bootstrap() {
      try {
        if (isSharedView) {
          const payload = await apiRequest(`/api/public/chat/${shareToken}/`);
          setSharedChat(payload);
          setShareNotFound(false);
        } else {
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
        }
      } catch (error) {
        if (isSharedView) {
          setShareNotFound(true);
          setSharedChat(null);
        } else {
          showToast("Workspace issue", error.message, "error");
        }
      } finally {
        setAuthReady(true);
      }
    }

    bootstrap();
  }, [isSharedView, shareToken]);

  async function loadWorkspace() {
    const [sessionsPayload, usagePayload, usageByModelPayload] = await Promise.all([
      apiRequest("/api/chat/sessions/"),
      apiRequest("/api/usage-stats/"),
      apiRequest("/api/usage-stats/models/"),
    ]);

    setSessions(sortSessions(sessionsPayload.sessions || []));
    setUsage(usagePayload);
    setUsageByModel(usageByModelPayload.models || []);

    if ((sessionsPayload.sessions || []).length === 0) {
      setActiveSessionId(null);
      setMessages([]);
      return;
    }

    if (!activeSessionId) {
      await handleSelectSession(sessionsPayload.sessions[0].id);
    }
  }

  async function loadLearningQuizzes() {
    const payload = await apiRequest("/api/learning/quizzes/");
    setQuizHistory(payload.quizzes || []);
  }

  async function refreshUsage() {
    try {
      const [usagePayload, usageByModelPayload] = await Promise.all([
        apiRequest("/api/usage-stats/"),
        apiRequest("/api/usage-stats/models/"),
      ]);
      setUsage(usagePayload);
      setUsageByModel(usageByModelPayload.models || []);
    } catch (error) {
      if (error.status !== 401) {
        showToast("Usage unavailable", error.message, "error");
      }
    }
  }

  function resetWorkspace() {
    abortStreamRequest();
    setSessions([]);
    setActiveSessionId(null);
    setCurrentPage("chat");
    setMessages([]);
    setUsage({
      total_input_tokens: 0,
      total_output_tokens: 0,
      total_tokens: 0,
    });
    setUsageByModel([]);
    setDraft("");
    setSessionSearch("");
    setUploadingDocument(false);
    setDocumentPanelOpen(false);
    resetStreamingState();
    setRegeneratingMessageId(null);
    setPinningSessionId(null);
    setSharingSessionId(null);
    setQuizHistory([]);
    setActiveQuiz(null);
    setQuizFocusQuestionId(null);
    setAnsweringQuizQuestionId(null);
    setQuizModalOpen(false);
    setLearningPath(null);
    clearEditState();
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
    if (sending) {
      return;
    }

    setLoadingConversation(true);

    try {
      const payload = await apiRequest(`/api/chat/sessions/${sessionId}/messages/`);
      startTransition(() => {
        setCurrentPage("chat");
        setActiveSessionId(payload.session.id);
        setSelectedModel(payload.session.model);
        setMessages(payload.messages || []);
        setDocumentPanelOpen(false);
        clearEditState();
      });
    } catch (error) {
      showToast("Unable to open chat", error.message, "error");
    } finally {
      setLoadingConversation(false);
    }
  }

  async function handleDeleteSession(sessionId) {
    if (sending) {
      return;
    }

    const confirmed = window.confirm("Delete this chat permanently?");
    if (!confirmed) {
      return;
    }

    try {
      await apiRequest(`/api/chat/sessions/${sessionId}/`, {
        method: "DELETE",
      });

      const remainingSessions = sessions.filter((session) => session.id !== sessionId);
      setSessions(sortSessions(remainingSessions));
      if (activeSessionId === sessionId) {
        setActiveSessionId(null);
        setMessages([]);
        clearEditState();
      }
      await refreshUsage();
      showToast("Chat deleted", "The conversation was removed.", "success");
    } catch (error) {
      showToast("Delete failed", error.message, "error");
    }
  }

  function handleNewChat() {
    if (sending) {
      return;
    }

    setCurrentPage("chat");
    setSidebarOpen(false);
    setActiveSessionId(null);
    setMessages([]);
    setDocumentPanelOpen(false);
    resetStreamingState();
    clearEditState();
    showToast("New chat", "Start a fresh private conversation.", "info");
  }

  function handleDraftKeyDown(event) {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      if (!sending) {
        event.currentTarget.form?.requestSubmit();
      }
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

    const streamController = new AbortController();
    let streamCompleted = false;

    setSending(true);
    setStoppingGeneration(false);
    setPendingPrompt(content);
    setStreamingResponse("");
    setDraft("");
    clearEditState();
    streamAbortRef.current = streamController;

    try {
      const response = await fetch("/api/chat/stream/", {
        method: "POST",
        credentials: "same-origin",
        signal: streamController.signal,
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCsrfToken(),
        },
        body: JSON.stringify({
          message: content,
          model: activeSession?.model || selectedModel,
          session_id: activeSessionId,
        }),
      });

      const contentType = response.headers.get("content-type") || "";
      const errorPayload = contentType.includes("application/json")
        ? await response.clone().json().catch(() => null)
        : null;

      if (!response.ok) {
        const error = new Error(errorPayload?.detail || "Unable to start generation.");
        error.status = response.status;
        throw error;
      }

      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error("Streaming is unavailable right now.");
      }

      const decoder = new TextDecoder();
      let buffer = "";
      let shouldRefreshUsage = false;

      while (true) {
        const { value, done } = await reader.read();
        if (done) {
          break;
        }

        buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
        const blocks = buffer.split("\n\n");
        buffer = blocks.pop() || "";

        for (const block of blocks) {
          if (!block.trim()) {
            continue;
          }

          const parsedEvent = parseSseBlock(block);
          if (!parsedEvent) {
            continue;
          }

          const { event, payload } = parsedEvent;

          if (event === "init") {
            setActiveStreamId(payload.stream_id || "");
            if (payload.session) {
              setActiveSessionId(payload.session.id);
              setSelectedModel(payload.session.model);
              setSessions((current) => upsertSession(current, payload.session));
            }
            continue;
          }

          if (event === "chunk") {
            setStreamingResponse((current) => current + (payload.content || ""));
            continue;
          }

          if (event === "error") {
            throw new Error(payload.detail || "Streaming failed.");
          }

          if (event === "done") {
            streamCompleted = true;
            shouldRefreshUsage = Boolean(payload.message);

            if (payload.session) {
              setActiveSessionId(payload.session.id);
              setSelectedModel(payload.session.model);
              setSessions((current) => upsertSession(current, payload.session));
            } else if (!activeSessionId) {
              setActiveSessionId(null);
              setMessages([]);
            }

            if (payload.message) {
              setMessages((current) => [...current, payload.message]);
            }

            if (payload.stopped) {
              showToast(
                "Generation stopped",
                payload.message
                  ? "The response was stopped and saved up to the last streamed chunk."
                  : "Generation stopped before any reply was saved.",
                "info",
              );
            }
          }
        }
      }

      if (buffer.trim()) {
        const parsedEvent = parseSseBlock(buffer);
        if (parsedEvent?.event === "done" && parsedEvent.payload.message) {
          const { payload } = parsedEvent;
          streamCompleted = true;
          setMessages((current) => [...current, payload.message]);
          if (payload.session) {
            setActiveSessionId(payload.session.id);
            setSelectedModel(payload.session.model);
            setSessions((current) => upsertSession(current, payload.session));
          }
          await refreshUsage();
        }
      } else if (shouldRefreshUsage) {
        await refreshUsage();
      }
    } catch (error) {
      if (error.name === "AbortError") {
        return;
      }

      setDraft((current) => current || content);
      if (error.status === 401) {
        showToast("Session expired", "Please sign in again to continue chatting.", "error");
        setCurrentUser(null);
        resetWorkspace();
        return;
      }
      showToast("Send failed", error.message, "error");
    } finally {
      if (!streamCompleted) {
        setStreamingResponse("");
      }
      resetStreamingState();
      abortStreamRequest();
    }
  }

  async function handleStopGeneration() {
    if (!sending || !activeStreamId || stoppingGeneration) {
      return;
    }

    setStoppingGeneration(true);

    try {
      await apiRequest(`/api/chat/streams/${activeStreamId}/stop/`, {
        method: "POST",
        body: JSON.stringify({}),
      });
    } catch (error) {
      setStoppingGeneration(false);
      showToast("Stop failed", error.message, "error");
    }
  }

  async function handleTogglePin(session) {
    if (!session?.id || sending || pinningSessionId) {
      return;
    }

    setPinningSessionId(session.id);

    try {
      const payload = await apiRequest(`/api/chat/sessions/${session.id}/pin/`, {
        method: "POST",
        body: JSON.stringify({ pinned: !session.is_pinned }),
      });

      setSessions((current) => upsertSession(current, payload.session));
      showToast(
        payload.session.is_pinned ? "Chat pinned" : "Chat unpinned",
        payload.session.is_pinned
          ? "This conversation will stay near the top of your sidebar."
          : "This conversation is back in normal chat order.",
        "success",
      );
    } catch (error) {
      showToast("Pin update failed", error.message, "error");
    } finally {
      setPinningSessionId(null);
    }
  }

  async function handleUploadDocument(event) {
    const file = event.target.files?.[0];
    event.target.value = "";

    if (!file) {
      return;
    }

    if (file.size > MAX_DOCUMENT_UPLOAD_BYTES) {
      showToast("PDF too large", "Only PDF files up to 10 MB can be uploaded.", "error");
      return;
    }

    const modelKey = activeSession?.model || selectedModel;
    const modelConfig = models.find((item) => item.key === modelKey);

    if (!modelConfig?.supports_documents) {
      showToast(
        "Document model required",
        "Start a new chat with a document-capable model before uploading a PDF.",
        "error",
      );
      return;
    }

    setUploadingDocument(true);

    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("model", modelKey);
      if (activeSessionId) {
        formData.append("session_id", activeSessionId);
      }

      const payload = await apiFormRequest("/api/chat/documents/", formData);
      setActiveSessionId(payload.session.id);
      setSelectedModel(payload.session.model);
      setSessions((current) => upsertSession(current, payload.session));
      setDocumentPanelOpen(false);
      if (!activeSessionId) {
        setMessages([]);
      }
      showToast(
        payload.reused ? "PDF already available" : "PDF ready",
        payload.reused
          ? `${payload.document.name} is already saved in this chat and has been selected.`
          : `${payload.document.name} was added and selected for this chat.`,
        "success",
      );
    } catch (error) {
      showToast("Upload failed", error.message, "error");
    } finally {
      setUploadingDocument(false);
    }
  }

  async function handleSelectDocument(documentId) {
    if (!activeSessionId || !documentId || selectingDocumentId) {
      return;
    }

    setSelectingDocumentId(documentId);
    try {
      const payload = await apiRequest(
        `/api/chat/sessions/${activeSessionId}/documents/${documentId}/select/`,
        {
          method: "POST",
          body: JSON.stringify({}),
        },
      );
      setSessions((current) => upsertSession(current, payload.session));
      showToast("PDF selected", `${payload.document.name} is now active for this chat.`, "success");
    } catch (error) {
      showToast("Selection failed", error.message, "error");
    } finally {
      setSelectingDocumentId(null);
    }
  }

  function handleStartEdit(message) {
    if (!message?.id || sending || regeneratingMessageId || savingEditMessageId) {
      return;
    }

    setEditingMessageId(message.id);
    setEditingDraft(message.user_message);
  }

  function handleCancelEdit() {
    clearEditState();
  }

  async function handleSaveEditedMessage(message) {
    if (!activeSessionId || !message?.id || !editingMessageId) {
      return;
    }

    const content = editingDraft.trim();
    if (!content) {
      showToast("Message required", "Edited message cannot be empty.", "error");
      return;
    }

    setSavingEditMessageId(message.id);

    try {
      const payload = await apiRequest(
        `/api/chat/sessions/${activeSessionId}/messages/${message.id}/edit/`,
        {
          method: "POST",
          body: JSON.stringify({ message: content }),
        },
      );

      setMessages(payload.messages || []);
      setSessions((current) => upsertSession(current, payload.session));
      await refreshUsage();
      clearEditState();
      showToast(
        "Message updated",
        payload.removed_count
          ? "The edited reply was regenerated and later messages were cleared to keep the chat consistent."
          : "The message was updated and regenerated successfully.",
        "success",
      );
    } catch (error) {
      if (error.status === 401) {
        showToast("Session expired", "Please sign in again to continue chatting.", "error");
        setCurrentUser(null);
        resetWorkspace();
        return;
      }
      showToast("Edit failed", error.message, "error");
    } finally {
      setSavingEditMessageId(null);
    }
  }

  async function handleToggleShare() {
    if (!activeSession || sharingSessionId || sending) {
      return;
    }

    setSharingSessionId(activeSession.id);

    try {
      const payload = await apiRequest(`/api/chat/sessions/${activeSession.id}/share/`, {
        method: "POST",
        body: JSON.stringify({ is_public: !activeSession.is_public }),
      });

      setSessions((current) => upsertSession(current, payload.session));

      if (payload.session.is_public && payload.session.share_url) {
        try {
          await copyText(buildAbsoluteUrl(payload.session.share_url));
          showToast("Chat shared", "Public read-only link copied to clipboard.", "success");
        } catch {
          showToast("Chat shared", "Public read-only link is ready to copy.", "success");
        }
      } else {
        showToast("Sharing disabled", "This conversation is private again.", "info");
      }
    } catch (error) {
      showToast("Share update failed", error.message, "error");
    } finally {
      setSharingSessionId(null);
    }
  }

  async function handleCopyShareLink() {
    if (!activeSession?.share_url) {
      return;
    }

    try {
      await copyText(buildAbsoluteUrl(activeSession.share_url));
      showToast("Link copied", "The public read-only chat link is in your clipboard.", "success");
    } catch {
      showToast("Copy failed", "Unable to copy the share link right now.", "error");
    }
  }

  async function handleRegenerateMessage(message) {
    if (!activeSessionId || !message?.id || regeneratingMessageId || sending) {
      return;
    }

    clearEditState();
    setRegeneratingMessageId(message.id);

    try {
      const payload = await apiRequest(
        `/api/chat/sessions/${activeSessionId}/messages/${message.id}/regenerate/`,
        {
          method: "POST",
          body: JSON.stringify({}),
        },
      );

      setMessages((current) =>
        current.map((item) => (item.id === payload.message.id ? payload.message : item)),
      );
      setSessions((current) => upsertSession(current, payload.session));
      await refreshUsage();
      showToast("Response regenerated", "A fresh AI reply was generated.", "success");
    } catch (error) {
      if (error.status === 401) {
        showToast("Session expired", "Please sign in again to continue chatting.", "error");
        setCurrentUser(null);
        resetWorkspace();
        return;
      }
      showToast("Regenerate failed", error.message, "error");
    } finally {
      setRegeneratingMessageId(null);
    }
  }

  async function handleStartQuiz(event) {
    event.preventDefault();
    const topic = quizTopic.trim();

    if (!topic) {
      showToast("Topic required", "Enter a topic before starting quiz mode.", "error");
      return;
    }

    setQuizLoading(true);

    try {
      const payload = await apiRequest("/api/learning/quizzes/create/", {
        method: "POST",
        body: JSON.stringify({
          topic,
          model: quizModel,
          question_count: Number(quizQuestionCount),
        }),
      });
      setActiveQuiz(payload.quiz);
      setQuizFocusQuestionId(payload.quiz.questions?.[0]?.id || null);
      setQuizModalOpen(false);
      setQuizHistory((current) => upsertQuizHistory(current, payload.quiz));
      showToast("Quiz ready", `Your ${payload.quiz.topic} quiz is ready to start.`, "success");
    } catch (error) {
      showToast("Quiz failed", error.message, "error");
    } finally {
      setQuizLoading(false);
    }
  }

  async function handleAnswerQuizQuestion(question, selectedOption) {
    if (!activeQuiz?.id || !question?.id || answeringQuizQuestionId) {
      return;
    }

    setAnsweringQuizQuestionId(question.id);

    try {
      const payload = await apiRequest(
        `/api/learning/quizzes/${activeQuiz.id}/questions/${question.id}/answer/`,
        {
          method: "POST",
          body: JSON.stringify({ selected_option: selectedOption }),
        },
      );
      setActiveQuiz(payload.quiz);
      setQuizFocusQuestionId(question.id);
      setQuizHistory((current) => upsertQuizHistory(current, payload.quiz));
      showToast(
        payload.question.is_correct ? "Correct answer" : "Answer recorded",
        payload.question.is_correct
          ? "Nice work. Your score has been updated."
          : `The right option was ${payload.question.correct_option}.`,
        payload.question.is_correct ? "success" : "info",
      );
      if (payload.quiz.is_completed) {
        setQuizModalOpen(false);
        showToast(
          "Quiz completed",
          `You scored ${payload.quiz.correct_answers}/${payload.quiz.total_questions}.`,
          "success",
        );
      }
    } catch (error) {
      showToast("Quiz answer failed", error.message, "error");
    } finally {
      setAnsweringQuizQuestionId(null);
    }
  }

  function handleContinueQuiz() {
    if (!activeQuiz?.questions?.length) {
      return;
    }

    const currentIndex = activeQuiz.questions.findIndex((item) => item.id === quizFocusQuestionId);
    if (activeQuiz.is_completed) {
      const nextQuestion = activeQuiz.questions[currentIndex + 1] || null;
      if (nextQuestion) {
        setQuizFocusQuestionId(nextQuestion.id);
      }
      return;
    }

    const nextQuestion = activeQuiz.questions.find((item) => !item.selected_option) || null;
    if (nextQuestion) {
      setQuizFocusQuestionId(nextQuestion.id);
    }
  }

  function handlePreviousQuiz() {
    if (!activeQuiz?.questions?.length) {
      return;
    }
    const currentIndex = activeQuiz.questions.findIndex((item) => item.id === quizFocusQuestionId);
    const previousQuestion = currentIndex > 0 ? activeQuiz.questions[currentIndex - 1] : null;
    if (previousQuestion) {
      setQuizFocusQuestionId(previousQuestion.id);
    }
  }

  async function handleOpenQuiz(quiz) {
    if (!quiz) {
      return;
    }

    try {
      const payload = await apiRequest(`/api/learning/quizzes/${quiz.id}/`);
      const resolvedQuiz = payload.quiz;
      const questions = resolvedQuiz.questions || [];
      const initialQuestion = resolvedQuiz.is_completed
        ? questions[0]
        : questions.find((item) => !item.selected_option) || questions[0];

      setActiveQuiz(resolvedQuiz);
      setQuizHistory((current) => upsertQuizHistory(current, resolvedQuiz));
      setQuizFocusQuestionId(initialQuestion?.id || null);
      setQuizModalOpen(true);
    } catch (error) {
      showToast("Quiz unavailable", error.message, "error");
    }
  }

  function handleLearningPathFormChange(event) {
    const { name, value } = event.target;
    setLearningPathForm((current) => ({ ...current, [name]: value }));
  }

  async function handleGenerateLearningPath(event) {
    event.preventDefault();
    const goal = learningPathForm.goal.trim();

    if (!goal) {
      showToast("Goal required", "Tell the assistant what you want to learn first.", "error");
      return;
    }

    setLearningPathLoading(true);

    try {
      const payload = await apiRequest("/api/learning/path/", {
        method: "POST",
        body: JSON.stringify(learningPathForm),
      });
      setLearningPath(payload.path);
      showToast("Roadmap ready", "Your personalized learning path has been generated.", "success");
    } catch (error) {
      showToast("Roadmap failed", error.message, "error");
    } finally {
      setLearningPathLoading(false);
    }
  }

  useEffect(() => {
    if (!currentUser || currentPage !== "learn") {
      return;
    }

    loadLearningQuizzes().catch((error) => {
      showToast("Learning tools unavailable", error.message, "error");
    });
  }, [currentPage, currentUser]);

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

  if (isSharedView) {
    return (
      <>
        <ToastViewport toasts={toasts} onDismiss={dismissToast} />
        <SharedChatPage
          branding={branding}
          sharePayload={sharedChat}
          shareNotFound={shareNotFound}
          theme={theme}
          onThemeToggle={() => setTheme((current) => (current === "dark" ? "light" : "dark"))}
        />
      </>
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
            searchValue={sessionSearch}
            busy={sending || Boolean(regeneratingMessageId)}
            pinnedCount={pinnedCount}
            pinningSessionId={pinningSessionId}
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
            onOpenLearn={() => {
              setCurrentPage("learn");
              setSidebarOpen(false);
            }}
            onSearchChange={(event) => setSessionSearch(event.target.value)}
            onSelect={(sessionId) => {
              setSidebarOpen(false);
              return handleSelectSession(sessionId);
            }}
            onTogglePin={handleTogglePin}
            onDelete={handleDeleteSession}
          />

          <main className="workspace">
            {currentPage === "chat" && documentPanelOpen ? (
              <button
                className="document-panel-backdrop"
                type="button"
                onClick={() => setDocumentPanelOpen(false)}
                aria-label="Close document panel"
              />
            ) : null}
            <header className="workspace-header">
              <div className="workspace-topbar">
                <div className="workspace-topline-left">
                  <button
                    className="secondary-button icon-button mobile-sidebar-toggle"
                    type="button"
                    onClick={() => setSidebarOpen((current) => !current)}
                    aria-label={sidebarOpen ? "Hide sidebar" : "Show sidebar"}
                    title={sidebarOpen ? "Hide sidebar" : "Show sidebar"}
                  >
                    <i className={`bi ${sidebarOpen ? "bi-x-lg" : "bi-list"}`} />
                  </button>
                  <p className="eyebrow">Authenticated workspace</p>
                </div>

                <div className="workspace-actions">
                  {currentPage === "chat" && activeSession ? (
                    <>
                      <button
                        className={`secondary-button icon-button desktop-action ${activeSession.is_public ? "is-active" : ""}`}
                        type="button"
                        onClick={handleToggleShare}
                        title={activeSession.is_public ? "Make chat private" : "Create public read-only link"}
                        aria-label={activeSession.is_public ? "Make chat private" : "Create public read-only link"}
                        disabled={Boolean(sharingSessionId)}
                      >
                        <i className={`bi ${sharingSessionId ? "bi-arrow-repeat" : activeSession.is_public ? "bi-globe2" : "bi-lock-fill"}`} />
                      </button>
                      <button
                        className="secondary-button icon-button desktop-action"
                        type="button"
                        onClick={handleCopyShareLink}
                        title="Copy share link"
                        aria-label="Copy share link"
                        disabled={!activeSession.is_public || !activeSession.share_url}
                      >
                        <i className="bi bi-link-45deg" />
                      </button>
                    </>
                  ) : null}
                  <ThemeToggle
                    theme={theme}
                    onToggle={() => setTheme((current) => (current === "dark" ? "light" : "dark"))}
                  />
                  <button
                    className="secondary-button icon-button desktop-action"
                    type="button"
                    onClick={handleLogout}
                    title="Logout"
                    aria-label="Logout"
                  >
                    <i className="bi bi-power" />
                  </button>
                  <div className="mobile-actions-shell">
                    <button
                      className={`secondary-button icon-button mobile-settings-toggle ${mobileActionsOpen ? "is-active" : ""}`}
                      type="button"
                      onClick={() => setMobileActionsOpen((current) => !current)}
                      title={mobileActionsOpen ? "Close quick actions" : "Open quick actions"}
                      aria-label={mobileActionsOpen ? "Close quick actions" : "Open quick actions"}
                    >
                      <i className={`bi ${mobileActionsOpen ? "bi-x-lg" : "bi-gear"} `} />
                    </button>
                    <div className={`mobile-actions-menu ${mobileActionsOpen ? "is-open" : ""}`}>
                      {currentPage === "chat" && activeSession ? (
                        <>
                          <button
                            className={`secondary-button icon-button ${activeSession.is_public ? "is-active" : ""}`}
                            type="button"
                            onClick={async () => {
                              await handleToggleShare();
                              setMobileActionsOpen(false);
                            }}
                            title={activeSession.is_public ? "Make chat private" : "Create public read-only link"}
                            aria-label={activeSession.is_public ? "Make chat private" : "Create public read-only link"}
                            disabled={Boolean(sharingSessionId)}
                          >
                            <i className={`bi ${sharingSessionId ? "bi-arrow-repeat" : activeSession.is_public ? "bi-globe2" : "bi-lock-fill"}`} />
                          </button>
                          <button
                            className="secondary-button icon-button"
                            type="button"
                            onClick={async () => {
                              await handleCopyShareLink();
                              setMobileActionsOpen(false);
                            }}
                            title="Copy share link"
                            aria-label="Copy share link"
                            disabled={!activeSession.is_public || !activeSession.share_url}
                          >
                            <i className="bi bi-link-45deg" />
                          </button>
                        </>
                      ) : null}
                      <button
                        className="secondary-button icon-button"
                        type="button"
                        onClick={async () => {
                          await handleLogout();
                          setMobileActionsOpen(false);
                        }}
                        title="Logout"
                        aria-label="Logout"
                      >
                        <i className="bi bi-power" />
                      </button>
                    </div>
                  </div>
                </div>
              </div>
              <div className="workspace-heading-copy">
                <h1>{currentPage === "profile" ? "Profile" : currentPage === "learn" ? "Learn" : activeSession?.title || "New conversation"}</h1>
                {currentPage === "profile" ? (
                  <p className="workspace-subtitle">
                    A separate page for this user’s account details and usage totals.
                  </p>
                ) : currentPage === "learn" ? (
                  <p className="workspace-subtitle">
                    Practice with quizzes and generate guided learning roadmaps inside your workspace.
                  </p>
                ) : null}
              </div>
            </header>

            {currentPage === "profile" ? (
              <ProfilePage currentUser={currentUser} usage={usage} usageByModel={usageByModel} sessions={sessions} theme={theme} />
            ) : currentPage === "learn" ? (
              <LearnPage
                models={models}
                quizTopic={quizTopic}
                quizModel={quizModel}
                quizQuestionCount={quizQuestionCount}
                quizLoading={quizLoading}
                activeQuiz={activeQuiz}
              quizHistory={quizHistory}
              quizFocusQuestionId={quizFocusQuestionId}
              answeringQuizQuestionId={answeringQuizQuestionId}
              quizModalOpen={quizModalOpen}
              learningPathForm={learningPathForm}
              learningPathLoading={learningPathLoading}
              learningPath={learningPath}
                onQuizTopicChange={(event) => setQuizTopic(event.target.value)}
                onQuizModelChange={(event) => setQuizModel(event.target.value)}
                onQuizQuestionCountChange={(event) => setQuizQuestionCount(event.target.value)}
                onStartQuiz={handleStartQuiz}
                onOpenQuiz={handleOpenQuiz}
                onCloseQuiz={() => setQuizModalOpen(false)}
                onAnswerQuizQuestion={handleAnswerQuizQuestion}
                onContinueQuiz={handleContinueQuiz}
                onPreviousQuiz={handlePreviousQuiz}
                onLearningPathFormChange={handleLearningPathFormChange}
                onGenerateLearningPath={handleGenerateLearningPath}
              />
            ) : (
              <>
                <section className="conversation-panel">
                <MessageList
                  activeSessionId={activeSessionId}
                  branding={branding}
                  messages={messages}
                  pendingPrompt={pendingPrompt}
                  streamingResponse={streamingResponse}
                  loadingConversation={loadingConversation}
                  editingMessageId={editingMessageId}
                  editingDraft={editingDraft}
                  regeneratingMessageId={regeneratingMessageId}
                  savingEditMessageId={savingEditMessageId}
                  onEditDraftChange={(event) => setEditingDraft(event.target.value)}
                  onStartEdit={handleStartEdit}
                  onCancelEdit={handleCancelEdit}
                  onSaveEdit={handleSaveEditedMessage}
                  onRegenerate={handleRegenerateMessage}
                />
              </section>

                <ChatComposer
                  draft={draft}
                  model={activeSession?.model || selectedModel}
                  models={models}
                  isLocked={Boolean(activeSession)}
                  sending={sending}
                  stoppingGeneration={stoppingGeneration}
                  documentOpen={documentPanelOpen}
                  documentAvailable={Boolean(getSessionDocuments(activeSession).length || models.length)}
                  onDraftChange={(event) => setDraft(event.target.value)}
                  onDraftKeyDown={handleDraftKeyDown}
                  onModelChange={(event) => setSelectedModel(event.target.value)}
                  onToggleDocument={() => setDocumentPanelOpen((current) => !current)}
                  onSubmit={handleSendMessage}
                  onStop={handleStopGeneration}
                />
                <DocumentPanel
                  activeSession={activeSession}
                  selectedModel={selectedModel}
                  models={models}
                  uploading={uploadingDocument}
                  selectingDocumentId={selectingDocumentId}
                  open={documentPanelOpen}
                  onClose={() => setDocumentPanelOpen(false)}
                  onUpload={handleUploadDocument}
                  onSelectDocument={handleSelectDocument}
                />
              </>
            )}
          </main>
        </div>
      </>
  );
}
