// A clarification card's answer is ordinary owner text: each block is one of
// the model's questions, then the owner's answer (dashboard answersMessage).
// It reads correctly only beside the model's own question. RTX Spark,
// 2026-10-16: OpenClaw started the answer to "Increase enemies by 10%" in a
// new native session (02269765 -> 8b4c4b17), so the model read its own
// question as the owner asking and edited nothing. The asking run leaves one
// private, bounded record per Portal chat (its session key is a pure function
// of the browser chat ID, so it survives native session replacement). The
// next owner run that answers exactly that card gets model-only context with
// the request. Owner text, and every classifier reading it, stays unchanged.
import * as fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createHash, randomBytes} from 'node:crypto';
import {isDeepStrictEqual} from 'node:util';
import {parseQuestions} from './questions-schema.mjs';

export const PENDING_CLARIFICATION_TTL_MS = 24 * 60 * 60 * 1000;
const SESSION = /^agent:[a-z0-9_-]+:openai-user:ods-[a-f0-9]{64}$/;
const MAX_BYTES = 65536;
const REQUEST_CHARS = 4000;
const ANSWER_CHARS = 2000;
const EARLIER_ANSWERS = 2;
const SHORTENED = ' [shortened]';
const RECORD_KEYS = 'createdAt,earlierAnswers,questions,request,runId,schemaVersion,sessionHash';
// Portal routing contracts appended after the owner's words (pixel-edge);
// a multipart turn can carry them after a single newline.
const PORTAL_CONTRACT = /\s*\[ODS (?:Portal|Pixel) delivery requirement:[\s\S]*$/;

function bounded(text, max) {
  const value = String(text ?? '').trim();
  return value.length <= max ? value : value.slice(0, max).replace(/[\ud800-\udbff]$/, '') + SHORTENED;
}

// The owner's own words of the run that asked, without Portal's contracts.
export function clarificationRequestText(text) {
  return bounded(String(text ?? '').replace(PORTAL_CONTRACT, ''), REQUEST_CHARS);
}

// True only for the card's own answer: the first question's exact text, a
// newline and an answer, then every later question after a blank line, in
// order (answersMessage, trimmed by the dashboard before sending).
export function answersClarification(questions, text) {
  if (!Array.isArray(questions) || !questions.length || typeof text !== 'string') return false;
  const value = text.replace(/\r\n/g, '\n').trimStart();
  let at = 0;
  for (const [index, item] of questions.entries()) {
    if (typeof item?.question !== 'string' || !item.question.trim()) return false;
    const marker = index ? `\n\n${item.question}\n` : `${item.question.trimStart()}\n`;
    const found = index ? value.indexOf(marker, at) : value.startsWith(marker) ? 0 : -1;
    if (found < 0 || (index && found <= at)) return false;
    at = found + marker.length;
  }
  return Boolean(value.slice(at).trim());
}

// before_prompt_build appendContext: beside the owner turn, never persisted
// as owner text (OpenClaw keeps hook context out of the transcript prompt).
export function clarificationAnswerContext(record) {
  return [
    "[ODS Portal note, not owner text: the owner message above answers the clarification questions you asked earlier. " +
      "Each block in it is one of your questions, then the owner's answer; those questions are your words, not the owner asking you.",
    'Original request:', record.request,
    ...(record.earlierAnswers.length ? ['Earlier clarification answers:', ...record.earlierAnswers] : []),
    'Carry out the original request now using these answers, unless an answer declines or changes it. ' +
      'This note does not set your reply language.]',
  ].join('\n');
}

export function createPendingClarifications({
  stateDir = path.join(process.env.OPENCLAW_STATE_DIR || path.join(os.homedir(), '.openclaw'), '.ods-pending-clarifications'),
  now = Date.now, ttlMs = PENDING_CLARIFICATION_TTL_MS, maximumSessions = 512,
} = {}) {
  const identity = sessionKey => typeof sessionKey === 'string' && SESSION.test(sessionKey)
    ? createHash('sha256').update(sessionKey).digest('hex') : null;
  const owned = info => process.platform === 'win32' || (info.uid === process.getuid() && (info.mode & 0o077) === 0);
  function directory(create = false) {
    if (!path.isAbsolute(stateDir)) throw new Error('Private clarification store required');
    if (create) fs.mkdirSync(stateDir, {recursive: true, mode: 0o700});
    const info = fs.lstatSync(stateDir);
    if (!info.isDirectory() || info.isSymbolicLink() || !owned(info)) throw new Error('Private clarification store required');
    return stateDir;
  }
  function read(file, id) {
    const before = fs.lstatSync(file);
    if (!before.isFile() || before.isSymbolicLink() || before.nlink !== 1 || before.size > MAX_BYTES || !owned(before)) {
      throw new Error('Invalid clarification record');
    }
    const fd = fs.openSync(file, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW || 0));
    let data;
    try {
      const info = fs.fstatSync(fd);
      if (info.ino !== before.ino || info.dev !== before.dev) throw new Error('Changed clarification record');
      const bytes = Buffer.alloc(MAX_BYTES + 1), length = fs.readSync(fd, bytes, 0, bytes.length, 0);
      if (length > MAX_BYTES) throw new Error('Invalid clarification record');
      data = JSON.parse(bytes.subarray(0, length).toString('utf8'));
    } finally { fs.closeSync(fd); }
    const questions = parseQuestions(data?.questions);
    if (!data || typeof data !== 'object' || Object.keys(data).sort().join() !== RECORD_KEYS || data.schemaVersion !== 1 ||
        data.sessionHash !== id || typeof data.runId !== 'string' || !data.runId || data.runId.length > 256 ||
        !Number.isSafeInteger(data.createdAt) || !questions || !isDeepStrictEqual(questions, data.questions) ||
        typeof data.request !== 'string' || !data.request || data.request.length > REQUEST_CHARS + SHORTENED.length ||
        !Array.isArray(data.earlierAnswers) || data.earlierAnswers.length > EARLIER_ANSWERS ||
        !data.earlierAnswers.every(text => typeof text === 'string' && text && text.length <= ANSWER_CHARS + SHORTENED.length)) {
      throw new Error('Invalid clarification record');
    }
    return data;
  }
  // Unanswered cards expire; an abandoned chat leaves nothing behind for long.
  function prune(folder) {
    const oldest = now() - ttlMs;
    for (const name of fs.readdirSync(folder)) {
      if (!/^[a-f0-9]{64}\.json$/.test(name)) continue;
      const file = path.join(folder, name);
      try { if (fs.lstatSync(file).mtimeMs < oldest) fs.unlinkSync(file); }
      catch (error) { if (error.code !== 'ENOENT') throw error; }
    }
  }
  return {
    // One pending card per chat: a newer question replaces the older one.
    remember({sessionKey, runId, questions, request, earlierAnswers = []}) {
      const id = identity(sessionKey), parsed = parseQuestions(questions), text = clarificationRequestText(request);
      if (!id || !parsed || typeof runId !== 'string' || !runId || runId.length > 256 || !text || !Array.isArray(earlierAnswers)) return false;
      const folder = directory(true), target = path.join(folder, `${id}.json`);
      prune(folder);
      if (!fs.existsSync(target) && fs.readdirSync(folder).filter(name => name.endsWith('.json')).length >= maximumSessions) return false;
      const value = {schemaVersion: 1, sessionHash: id, runId, createdAt: now(), request: text, questions: parsed,
        earlierAnswers: earlierAnswers.map(answer => bounded(String(answer ?? '').replace(PORTAL_CONTRACT, ''), ANSWER_CHARS))
          .filter(Boolean).slice(-EARLIER_ANSWERS)};
      const temporary = path.join(folder, `.write-${randomBytes(16).toString('hex')}`);
      try {
        const fd = fs.openSync(temporary, fs.constants.O_WRONLY | fs.constants.O_CREAT | fs.constants.O_EXCL, 0o600);
        try { fs.writeFileSync(fd, JSON.stringify(value)); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
        fs.renameSync(temporary, target);
      } finally { fs.rmSync(temporary, {force: true}); }
      return true;
    },
    // Consumed by the first owner run that reads it, answer or not: the card
    // is no longer answerable once a later message exists in the chat.
    take(sessionKey) {
      const id = identity(sessionKey);
      if (!id) return null;
      let folder;
      try { folder = directory(); } catch (error) { if (error.code === 'ENOENT') return null; throw error; }
      const file = path.join(folder, `${id}.json`);
      let record;
      try { record = read(file, id); }
      catch (error) {
        if (error.code === 'ENOENT') { prune(folder); return null; }
        fs.rmSync(file, {force: true}); throw error;
      }
      fs.unlinkSync(file);
      prune(folder);
      // A minute of clock skew is tolerated; an older or future record is not.
      const age = now() - record.createdAt;
      return age >= -60000 && age <= ttlMs ? record : null;
    },
  };
}
