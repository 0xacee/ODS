import { isDeepStrictEqual } from "node:util";

const record = (value) => Boolean(value) && typeof value === "object" && !Array.isArray(value);

const MAX_SEARCH_TEXT_CHARS = 256 * 1024;
// Match the pinned native after-tool sanitizer; projection must not expand its
// model-facing text allowance, even when structured details remain complete.
const NATIVE_SEARCH_TEXT_CHARS = 8_000;
function nativeSearchText(text) {
  if (text.length <= NATIVE_SEARCH_TEXT_CHARS) return text;
  let end = NATIVE_SEARCH_TEXT_CHARS;
  const high = text.charCodeAt(end - 1), low = text.charCodeAt(end);
  if (high >= 0xD800 && high <= 0xDBFF && low >= 0xDC00 && low <= 0xDFFF) end -= 1;
  return `${text.slice(0, end)}\n…(truncated)…`;
}

// The native web tool serializes its structured payload as one JSON block.
// Remove only excerpts that are already present byte-for-byte as that same
// result's description. Keep every unique excerpt and the original receipt.
function deduplicatedSearchContent(result, native = false) {
  if (!record(result) || !record(result.details) ||
      !Array.isArray(result.content) || result.content.length !== 1 ||
      result.content[0]?.type !== "text" || typeof result.content[0].text !== "string" ||
      result.content[0].text.length > MAX_SEARCH_TEXT_CHARS) return undefined;
  let payload;
  try { payload = JSON.parse(result.content[0].text); }
  catch {
    // Only the exact pinned sanitizer output can stand in for complete JSON.
    // Arbitrary partial text or differently redacted details are not evidence.
    if (!native) return undefined;
    let serialized;
    try {
      serialized = JSON.stringify(result.details, null, 2);
      if (typeof serialized !== "string" || !isDeepStrictEqual(JSON.parse(serialized), result.details)) return undefined;
    } catch { return undefined; }
    if (serialized.length <= NATIVE_SEARCH_TEXT_CHARS || serialized.length > MAX_SEARCH_TEXT_CHARS ||
        result.content[0].text !== nativeSearchText(serialized)) return undefined;
    payload = result.details;
  }
  if (!record(payload) || !isDeepStrictEqual(payload, result.details) ||
      typeof payload.provider !== "string" || !Array.isArray(payload.results) ||
      payload.results.length > 40) return undefined;
  let changed = false;
  const results = [];
  for (const row of payload.results) {
    if (!record(row)) return undefined;
    if (!Object.hasOwn(row, "excerpts")) { results.push(row); continue; }
    if (typeof row.description !== "string" || !Array.isArray(row.excerpts) ||
        !row.excerpts.every((text) => typeof text === "string")) return undefined;
    const excerpts = row.excerpts.filter((text) => text !== row.description);
    if (excerpts.length === row.excerpts.length) { results.push(row); continue; }
    changed = true;
    const projected = { ...row, excerpts };
    if (excerpts.length === 0) delete projected.excerpts;
    results.push(projected);
  }
  if (!changed) return undefined;
  const text = JSON.stringify({ ...payload, results }, null, 2);
  return [{ ...result.content[0], text: native ? nativeSearchText(text) : text }];
}

// Called only after exact native call/run/params binding by the guard. Snapshot
// before framework persistence truncation. The native hook may already have
// capped text; retain only an exactly verified serialization of its details.
export function captureNativeWebSearchResult(result) {
  if (!deduplicatedSearchContent(result, true)) return undefined;
  try { return structuredClone(result); }
  catch { return undefined; }
}

export function projectNativeWebSearchResult(message, result) {
  if (!record(message) || message.role !== "toolResult" || message.toolName !== "web_search") return undefined;
  const content = deduplicatedSearchContent(result, true);
  if (!content) return undefined;
  return { ...message, ...(message.isError === true || result.isError === true ? { isError: true } : {}),
    content, details: result.details };
}

// Preserve native evidence blocks instead of serializing them inside a second
// JSON document. The caller binds this framework envelope to the exact call.
export function projectWebResult(message, envelope) {
  if (!record(message) || message.toolName !== "tool_call" || !record(envelope)) return undefined;
  const { tool, result } = envelope;
  if (!record(tool) || !record(result) || tool.source !== "openclaw" ||
      tool.sourceName !== "core" || !["web_search", "web_fetch"].includes(tool.name) ||
      tool.id !== `openclaw:core:${tool.name}`) return undefined;
  const content = result.content;
  if (!Array.isArray(content) || content.length === 0 ||
      !content.every((block) => record(block) && block.type === "text" && typeof block.text === "string")) {
    return undefined;
  }
  const metadata = { ...result };
  delete metadata.content;
  if (content.length === 1 && record(result.details)) {
    let duplicate = false;
    try { duplicate = isDeepStrictEqual(JSON.parse(content[0].text), result.details); }
    catch { /* Plain text is not a duplicate structured payload. */ }
    if (duplicate) delete metadata.details;
    else if (result.details.aggregated === content[0].text) {
      metadata.details = { ...result.details };
      delete metadata.details.aggregated;
    }
  }
  const failed = message.isError === true || result.isError === true;
  const identity = { id: tool.id, source: tool.source, sourceName: tool.sourceName, name: tool.name };
  return {
    ...message,
    ...(failed ? { isError: true } : {}),
    content: [
      { type: "text", text: JSON.stringify({ tool: identity, result: metadata, ...(failed ? { isError: true } : {}) }) },
      ...(tool.name === "web_search" ? deduplicatedSearchContent(result) ?? content : content).map((block) => ({ ...block })),
    ],
    details: envelope,
  };
}
