"use strict";

// Vane v1.12.2 rewrites every bracket pair before Markdown rendering. On a
// research answer this turns Python lists inside code fences into citations.
// Patch only the exact pinned client expression; an unknown bundle must not
// silently serve the broken renderer.
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
const { renderCitations } = require("./citation-renderer");

const DEFAULT_ROOT = "/home/vane/public/_next/static/chunks";
const KNOWN_CHUNK = "1220-5cd2adbf287bf784.js";
const KNOWN_SHA256 = "24028fd3cee772aabfb5f836f8ced901a6a155c3c302b898401e3f863eef801d";
const TRUSTED_CHUNKS = Object.freeze({ [KNOWN_CHUNK]: KNOWN_SHA256 });
const STRICT_HEADER = '"use strict";';
const ORIGINAL = 's=l.length>0?s.replace(/\\[([^\\]]+)\\]/g,(e,t)=>t.split(",").map(e=>e.trim()).map(e=>{let t=parseInt(e);if(isNaN(t)||t<=0)return`[${e}]`;let r=l[t-1],a=r?.metadata?.url;return a?`<citation href="${a}">${e}</citation>`:""}).join("")):s.replace(d,"")';
const CALL = "s=self.__odsVaneCitationRender20261003(s,l)";
const PRELUDE = `self.__odsVaneCitationRender20261003=${renderCitations.toString()};\n`;

function occurrences(text, fragment) {
  return text.split(fragment).length - 1;
}

function sha256(text) {
  return crypto.createHash("sha256").update(text).digest("hex");
}

function patchClientChunk(root = DEFAULT_ROOT, trustedChunks = TRUSTED_CHUNKS) {
  const candidates = [];
  for (const name of fs.readdirSync(root)) {
    if (!name.endsWith(".js")) continue;
    const file = path.join(root, name);
    if (!fs.lstatSync(file).isFile()) continue;
    const text = fs.readFileSync(file, "utf8");
    if (text.includes(ORIGINAL) || text.includes(CALL) || text.includes("__odsVaneCitationRender20261003")) {
      candidates.push({ file, name, text });
    }
  }
  if (candidates.length !== 1) {
    throw new Error(`expected one Vane citation chunk in ${root}; found ${candidates.length}`);
  }

  const { file, name, text } = candidates[0];
  const expectedHash = trustedChunks[name];
  if (!expectedHash) throw new Error(`unqualified Vane citation chunk: ${file}`);
  const originalCount = occurrences(text, ORIGINAL);
  const patchedCount = occurrences(text, CALL);
  if (text.startsWith(STRICT_HEADER + PRELUDE) && originalCount === 0 && patchedCount === 1) {
    // Prove the complete patched bytes derive from the audited original, not
    // merely that a marker and one call survived a partial rewrite.
    const restored = STRICT_HEADER + text.slice((STRICT_HEADER + PRELUDE).length).replace(CALL, ORIGINAL);
    if (sha256(restored) !== expectedHash) throw new Error(`patched Vane client hash mismatch in ${file}`);
    return { file, changed: false };
  }
  if (!text.startsWith(STRICT_HEADER) || originalCount !== 1 || patchedCount !== 0 || text.includes("__odsVaneCitationRender20261003")) {
    throw new Error(`Vane citation renderer has an unknown or partial shape in ${file}`);
  }
  if (sha256(text) !== expectedHash) throw new Error(`pinned Vane client hash mismatch in ${file}`);

  const patched = STRICT_HEADER + PRELUDE + text.slice(STRICT_HEADER.length).replace(ORIGINAL, CALL);
  const temporary = `${file}.ods-${process.pid}.tmp`;
  try {
    fs.writeFileSync(temporary, patched, { mode: fs.statSync(file).mode & 0o777 });
    fs.renameSync(temporary, file);
  } finally {
    if (fs.existsSync(temporary)) fs.unlinkSync(temporary);
  }
  return { file, changed: true };
}

if (require.main === module) {
  try {
    const result = patchClientChunk(process.argv[2] || DEFAULT_ROOT);
    process.stderr.write(`[ods-perplexica] client citations ${result.changed ? "patched" : "already patched"}: ${result.file}\n`);
  } catch (error) {
    process.stderr.write(`[ods-perplexica] ERROR: client citation patch failed: ${error.message}\n`);
    process.exitCode = 1;
  }
}

module.exports = { patchClientChunk, ORIGINAL, CALL, PRELUDE, KNOWN_CHUNK, KNOWN_SHA256 };
