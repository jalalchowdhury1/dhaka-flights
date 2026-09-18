#!/usr/bin/env node
/**
 * Jev server — ONE long-lived process per run, line-delimited JSON over
 * stdin/stdout. Each stdin line is a request; each stdout line is a reply.
 *
 *   in : {"id": n, "instructions": "...", "state": "...", "candidates": ["...", ...]}
 *   out: {"id": n, "choice": "...", "index": i, "p": 0.93, "ms": 142}
 *        {"id": n, "choice": null, "index": -1, "p": 0, "ms": 0, "error": "..."}
 *
 * A {"sites": [...]} batch line answers one reply line per site (same shape).
 * Requests are handled concurrently; replies carry the request id, so the
 * client matches on id, not on order.
 */
import { createInterface } from 'node:readline';
import { experimental_evaluate as evaluate } from 'ai';
import { gateway } from '@ai-sdk/gateway';

let autoId = 0;

async function pick(req) {
  const id = req.id ?? ++autoId;
  const candidates = Array.isArray(req.candidates) ? req.candidates : [];
  if (candidates.length === 0) {
    return { id, ms: 0, choice: null, index: -1, p: 0, error: 'no-candidates' };
  }
  if (candidates.length === 1) {
    return { id, ms: 0, choice: candidates[0], index: 0, p: 1 };
  }
  const t0 = performance.now();
  try {
    const result = await evaluate({
      model: gateway.evaluationModel('typesafe-ai/jev'),
      state: req.state || `Real accessibility-tree elements read from the live ${req.site || 'page'} right now.`,
      questions: {
        pick: {
          type: 'choice',
          instructions: req.instructions || 'Pick the element that is the correct match.',
          criteria: Object.fromEntries(candidates.map((c) => [c, c])),
        },
      },
    });
    const ms = Math.round(performance.now() - t0);
    const choice = result.answers.pick.choice;
    const index = candidates.indexOf(choice);
    const p = result.answers.pick.probabilities?.[choice] ?? 0;
    return { id, ms, choice, index, p };
  } catch (err) {
    const ms = Math.round(performance.now() - t0);
    return { id, ms, choice: null, index: -1, p: 0, error: String(err?.message || err) };
  }
}

function reply(obj) {
  process.stdout.write(JSON.stringify(obj) + '\n');
}

const pending = new Set();
const rl = createInterface({ input: process.stdin, crlfDelay: Infinity });
rl.on('line', (line) => {
  line = line.trim();
  if (!line) return;
  let req;
  try {
    req = JSON.parse(line);
  } catch (e) {
    reply({ id: null, ms: 0, choice: null, index: -1, p: 0, error: `bad-json: ${e.message}` });
    return;
  }
  const reqs = Array.isArray(req.sites) ? req.sites : [req];
  for (const r of reqs) {
    const job = pick(r).then(reply).finally(() => pending.delete(job));
    pending.add(job);
  }
});
// stdin EOF = the client is done; answer what is still in flight, then exit.
rl.on('close', () => Promise.allSettled([...pending]).then(() => process.exit(0)));
