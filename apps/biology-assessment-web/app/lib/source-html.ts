const ALLOWED_TAGS = new Set([
  "h2", "h3", "h4", "h5", "h6", "p", "table", "tr", "th", "td", "br", "strong",
]);
const DISCARD_CONTENT = new Set(["script", "style", "iframe", "object", "embed", "template"]);
const RAW_TEXT = new Set(["script", "style", "iframe"]);

function prepareText(text: string): string {
  // Character references stay in text: decoding them never creates markup.
  return text.replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(
    /☑|&#(?:0*9745|x0*2611);/gi,
    '<span class="sourceCheck" aria-label="선택됨">☑</span>',
  );
}

function allowedAttributes(tag: string, attributes: string): string {
  const result = new Map<string, string>();
  const pattern = /\s+([^\s=/'"<>`]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?/gy;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(attributes))) {
    const name = match[1].toLowerCase();
    const value = match[2] ?? match[3] ?? match[4] ?? "";
    if ((tag === "th" || tag === "td") && (name === "rowspan" || name === "colspan")) {
      if (/^(?:[1-9]|[1-4][0-9]|50)$/.test(value) && !result.has(name)) {
        result.set(name, value);
      }
    } else if (tag === "p" && name === "class" && value === "source-list-item") {
      result.set(name, value);
    }
  }
  return Array.from(result, ([name, value]) => ` ${name}="${value}"`).join("");
}

/**
 * Serialize only the source HTML allowlist, without a browser DOM or a raw-HTML
 * fallback. The same tokenizer runs during SSR and hydration, without parser
 * repairs (such as moving table rows) in this presentation layer.
 * Every emitted tag/attribute is fixed or validated; other text is escaped.
 */
export function prepareSourceHtml(html: string): string {
  const tokens = /<!--[\s\S]*?(?:-->|$)|<![^>]*(?:>|$)|<\?[^>]*(?:>|$)|<\/?([a-z][a-z0-9:-]*)(?=[\s/>])((?:[^<>"']|"[^"]*"|'[^']*')*)>/gi;
  const discarded: string[] = [];
  const output: string[] = [];
  let cursor = 0;
  let match: RegExpExecArray | null;

  while ((match = tokens.exec(html))) {
    if (!discarded.length) output.push(prepareText(html.slice(cursor, match.index)));
    cursor = tokens.lastIndex;
    if (!match[1]) continue; // Comments, declarations and processing instructions.

    const tag = match[1].toLowerCase();
    const closing = match[0].startsWith("</");
    if (DISCARD_CONTENT.has(tag)) {
      if (closing) {
        const index = discarded.lastIndexOf(tag);
        if (index !== -1) discarded.length = index;
      } else if (RAW_TEXT.has(tag) || tag === "embed") {
        const end = new RegExp(`</${tag}(?=[\\s/>])[^>]*>`, "gi");
        end.lastIndex = cursor;
        if (end.exec(html)) {
          tokens.lastIndex = cursor = end.lastIndex;
        } else if (tag !== "embed") {
          tokens.lastIndex = cursor = html.length;
        }
        // An unpaired embed is a void element and has no contents.
      } else {
        discarded.push(tag);
      }
      continue;
    }
    if (discarded.length || !ALLOWED_TAGS.has(tag)) continue;

    if (closing) {
      if (tag === "br") continue;
      output.push(`</${tag}>`);
      if (tag === "table") output.push("</div>");
    } else {
      if (tag === "table") output.push('<div class="sourceTableScroll">');
      output.push(`<${tag}${allowedAttributes(tag, match[2])}>`);
    }
  }
  if (!discarded.length) output.push(prepareText(html.slice(cursor)));
  return output.join("");
}
