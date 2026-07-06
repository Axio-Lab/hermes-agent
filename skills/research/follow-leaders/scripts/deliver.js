#!/usr/bin/env node
/**
 * deliver.js
 *
 * Takes the final remixed digest (markdown text, produced by the agent using the
 * prompts/ files) on stdin and sends it via the configured delivery method.
 *
 * Usage:
 *   cat digest.md | node deliver.js <industry-slug>
 *
 * Reads delivery config from ~/.follow-leaders/config.json (profiles[].delivery)
 * and any credentials from ~/.follow-leaders/.env (TELEGRAM_BOT_TOKEN,
 * TELEGRAM_CHAT_ID, RESEND_API_KEY). If delivery.method is "stdout", it just
 * prints the digest back out — this is what happens for in-chat / on-demand use,
 * where the calling agent shows the digest directly instead of routing it through
 * this script at all.
 */

const fs = require('fs');
const path = require('path');
const os = require('os');
const https = require('https');

const HOME = os.homedir();
const CONFIG_PATH = path.join(HOME, '.follow-leaders', 'config.json');
const ENV_PATH = path.join(HOME, '.follow-leaders', '.env');

function loadEnv() {
  const env = {};
  if (fs.existsSync(ENV_PATH)) {
    const lines = fs.readFileSync(ENV_PATH, 'utf8').split('\n');
    for (const line of lines) {
      const m = line.match(/^([A-Z_]+)=(.*)$/);
      if (m) env[m[1]] = m[2];
    }
  }
  return env;
}

function postJson(hostname, pathName, headers, bodyObj) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify(bodyObj);
    const req = https.request(
      {
        hostname,
        path: pathName,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body), ...headers },
      },
      (res) => {
        let data = '';
        res.on('data', (c) => (data += c));
        res.on('end', () => resolve({ status: res.statusCode, data }));
      }
    );
    req.on('error', reject);
    req.write(body);
    req.end();
  });
}

async function deliverTelegram(digest, env, profile) {
  const token = env.TELEGRAM_BOT_TOKEN;
  const chatId = profile.delivery.telegramChatId;
  if (!token || !chatId) {
    console.error('Telegram delivery configured but TELEGRAM_BOT_TOKEN or telegramChatId missing.');
    return;
  }
  await postJson('api.telegram.org', `/bot${token}/sendMessage`, {}, {
    chat_id: chatId,
    text: digest,
    parse_mode: 'Markdown',
  });
}

async function deliverEmail(digest, env, profile) {
  const apiKey = env.RESEND_API_KEY;
  if (!apiKey || !profile.delivery.email) {
    console.error('Email delivery configured but RESEND_API_KEY or delivery.email missing.');
    return;
  }
  await postJson('api.resend.com', '/emails', { Authorization: `Bearer ${apiKey}` }, {
    from: 'digest@follow-leaders.local',
    to: profile.delivery.email,
    subject: `${profile.industry} Leaders Digest`,
    text: digest,
  });
}

async function main() {
  const slug = process.argv[2];
  const digest = fs.readFileSync(0, 'utf8'); // stdin
  if (!fs.existsSync(CONFIG_PATH)) {
    console.log(digest); // nothing configured yet — just echo it
    return;
  }
  const config = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
  const profile = (config.profiles || []).find((p) => p.industrySlug === slug);
  if (!profile) {
    console.log(digest);
    return;
  }
  const env = loadEnv();

  switch (profile.delivery.method) {
    case 'telegram':
      await deliverTelegram(digest, env, profile);
      break;
    case 'email':
      await deliverEmail(digest, env, profile);
      break;
    case 'stdout':
    default:
      console.log(digest);
      break;
  }
}

main();
