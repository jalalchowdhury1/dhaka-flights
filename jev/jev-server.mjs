#!/usr/bin/env node
/**
 * Jev Server - A long-lived Node process that picks elements from accessibility trees.
 * 
 * This is the jev-server.mjs extracted from browser-use/jev-ultrafast and
 * ~/.claude/skills/webai/jev-pick.mjs reference code.
 * 
 * Request format (line-delimited JSON):
 *   {"id": n, "site": "google-flights", "instructions": "Pick the airport...", "state": "...", "candidates": ["..."]}
 * 
 * Response format (line-delimited JSON):
 *   {"id": n, "choice": "...", "index": i, "p": 0.93, "ms": 142}
 *   or
 *   {"id": n, "error": "..."}
 * 
 * Request per site format (as per brief):
 *   {"sites": [{"name":"...", "instructions":"...","state":"...","candidates":["..."]}]}
 */

import { experimental_evaluate as evaluate } from 'ai';
import { gateway } from '@ai-sdk/gateway';

let currentId = 0;

const chunks = [];
process.stdin.setEncoding('utf8');

process.stdin.on('data', (chunk) => {
  chunks.push(chunk);
});

process.stdin.on('end', async () => {
  let input;
  try {
    input = JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } catch (e) {
    console.error(JSON.stringify({ id: ++currentId, error: `Invalid JSON input: ${e.message}` }));
    process.exit(1);
  }

  // Handle the sites format from the brief
  const sites = input.sites || [input];
  const siteArray = Array.isArray(sites) ? sites : [sites];
  
  const results = await Promise.all(
    siteArray.map(async (site, idx) => {
      const id = site.id || ++currentId;
      
      // Handle empty or missing candidates
      if (!site.candidates || site.candidates.length === 0) {
        return {
          id,
          ms: 0,
          choice: null,
          index: -1,
          p: 0,
          error: 'no-candidates'
        };
      }
      
      // Single candidate - no need to call Jev
      if (site.candidates.length === 1) {
        return {
          id,
          ms: 0,
          choice: site.candidates[0],
          index: 0,
          p: 1
        };
      }
      
      // Use Jev for multiple candidates
      const t0 = performance.now();
      try {
        const result = await evaluate({
          model: gateway.evaluationModel('typesafe-ai/jev'),
          state: site.state || `Real accessibility-tree elements read from the live ${site.name || 'page'} right now.`,
          questions: {
            pick: {
              type: 'choice',
              instructions: site.instructions || 'Pick the element that is the correct match.',
              criteria: Object.fromEntries(site.candidates.map((c) => [c, c])),
            },
          },
        });
        
        const ms = performance.now() - t0;
        const choice = result.answers.pick.choice;
        const index = site.candidates.indexOf(choice);
        const p = result.answers.pick.probabilities[choice];
        
        return {
          id,
          ms,
          choice,
          index,
          p
        };
      } catch (err) {
        const ms = performance.now() - t0;
        return {
          id,
          ms,
          choice: null,
          index: -1,
          p: 0,
          error: String(err.message || err)
        };
      }
    })
  );
  
  // Output results line by line
  for (const r of results) {
    console.log(JSON.stringify(r));
  }
});