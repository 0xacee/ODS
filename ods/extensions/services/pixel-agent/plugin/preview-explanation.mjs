// Keep the agent's own explanation when a workspace preview check fails.
//
// A failed preview outcome (a browser or interaction check that did not pass,
// requested text missing, a stale or unpublished snapshot) used to replace the
// agent's whole final reply with the host's delivery text. On the RTX Spark
// (Elf of Doom, round 9) that hid the agent's correct root-cause explanation:
// the owner saw only "The attempted preview interaction checks have not
// passed browser inspection ... Your preview is ready."
//
// Now the agent's final prose comes first and the host facts follow it,
// unchanged, under a fixed label. The prose is delivered as written and is
// never evidence: the outcome stays failed, every host failure line and the
// preview receipt still follow it, and when the prose says the work passed,
// works or is fixed, the host note says plainly that the checks did not all
// pass (PREVIEW_CLAIM_NOTE).
//
// The prose passes the filter every host-composed answer passes
// (deliverableAnswer in progress-finalization.mjs). It is dropped, and the host
// delivery stands alone as before, when it is empty or too short, silent
// (NO_REPLY), tool-call text, when it links any local URL other than this
// outcome's own preview, or when it carries the host label below (a copied or
// imitated host note must not read as Portal's own). A short promise ("I'll
// fix line 748 next") is kept: unlike a tool-limit answer, the run ended on
// its own here. Everything added here is fixed English text.
import { deliverableAnswer } from './progress-finalization.mjs';
import { silentReplyText } from './owner-visible-reply.mjs';

export const PREVIEW_CHECK_LABEL = '**Portal check:**';
// True for every failed outcome, including one where some checks passed.
export const PREVIEW_CLAIM_NOTE =
  "Portal's checks did not all pass: where the reply above says the work passed, works or is fixed, that is not verified.";

// The combined reply is host verification text (ingress limit: 32 KiB). Leave
// room for the extension and progress-lane notes that can follow it.
const MAX_EXPLAINED_CHARS = 24 * 1024;

// English success wording. A clause with a negation, a condition or a plan is
// not a claim ("not fixed yet", "if it works", "this should fix it").
const SUCCESS_WORD = /\b(?:works|worked|working|fixed|resolved|verified|confirmed|pass(?:es|ed)?|passing|succeeded|successful(?:ly)?)\b/i;
const NOT_A_CLAIM = /\b(?:not|no|never|cannot|unable|unverified|unconfirmed|without|unless|if|whether|until|once|yet|should|could|might|may|would|will|need(?:s|ed)?|try|tried|trying|hope(?:fully)?|fail(?:s|ed|ing)?)\b|n['’]t\b/i;

// Only the reply's own statements: code, inline code and quotes are examples.
export function claimsVerifiedSuccess(text) {
  const prose = String(text ?? '')
    .replace(/```[\s\S]*?(?:```|$)|~~~[\s\S]*?(?:~~~|$)/g, '\n')
    .replace(/`[^`\n]*`/g, ' ')
    .replace(/^[ \t]*>.*$/gm, '');
  return prose.split(/[.!?;:\n]+|,\s*(?:but|although|though|however|yet)\b/i)
    .some(clause => SUCCESS_WORD.test(clause) && !NOT_A_CLAIM.test(clause));
}

// Returns `result` with the agent's prose ahead of its host text, or `result`
// itself when it is not a failed outcome or the prose cannot be delivered.
export function explainedPreviewDelivery(result, replyText) {
  if (result?.status !== 'failed' || typeof result.text !== 'string' || !result.text) return result;
  if (typeof replyText !== 'string' || silentReplyText(replyText)) return result;
  const answer = deliverableAnswer(replyText, {localUrlsForbidden: true,
    allowedUrls: result.preview?.url ? [result.preview.url] : []});
  if (!answer || /\bportal check:/i.test(answer)) return result;
  // Close an unterminated fence so the host note and receipt stay outside it.
  const fences = [...answer.matchAll(/^[ \t]{0,3}(`{3,}|~{3,})/gm)].map(match => match[1]);
  const closing = fences.length % 2 ? `\n${fences.at(-1)}` : '';
  const claim = claimsVerifiedSuccess(answer) ? `${PREVIEW_CLAIM_NOTE}\n\n` : '';
  const text = `${answer}${closing}\n\n${PREVIEW_CHECK_LABEL} ${claim}${result.text}`;
  return text.length > MAX_EXPLAINED_CHARS ? result : {...result, text};
}
