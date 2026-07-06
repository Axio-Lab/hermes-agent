#!/usr/bin/env node
/**
 * fetch-content.js
 *
 * Pulls raw content for one industry profile from free, public sources only:
 *   - YouTube: per-channel RSS feed (no API key)
 *   - Reddit: public .json listing endpoints (no API key)
 *   - X/Twitter, LinkedIn, Instagram, TikTok, Facebook, blogs, newsletters: NOT
 *     fetched here — the agent resolves these via Composio (Verxio Connections) or
 *     web_search/web_fetch. This script passes profile lists through in raw JSON.
 *
 * Usage:
 *   node fetch-content.js <industry-slug>
 *
 * Output:
 *   Writes raw JSON to ~/.follow-leaders/state/<industry-slug>-raw.json
 *   Also updates ~/.follow-leaders/state/<industry-slug>-seen.json to dedupe
 *   across runs (mirrors the state-feed.json pattern from the original skill).
 */

const fs = require('fs');
const path = require('path');
const os = require('os');
const https = require('https');

const HOME = os.homedir();
const STATE_DIR = path.join(HOME, '.follow-leaders', 'state');
const SKILL_DIR = path.resolve(__dirname, '..');

function fetchUrl(url) {
  return new Promise((resolve, reject) => {
    https.get(url, { headers: { 'User-Agent': 'follow-leaders-skill/1.0' } }, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        return resolve(fetchUrl(res.headers.location));
      }
      let data = '';
      res.on('data', (chunk) => (data += chunk));
      res.on('end', () => resolve(data));
    }).on('error', reject);
  });
}

async function fetchYoutubeFeed(channelId) {
  if (!channelId) return null;
  const url = `https://www.youtube.com/feeds/videos.xml?channel_id=${channelId}`;
  try {
    return await fetchUrl(url);
  } catch (err) {
    console.error(`YouTube fetch failed for ${channelId}:`, err.message);
    return null;
  }
}

async function fetchRedditTop(subreddit) {
  const url = `https://www.reddit.com/r/${subreddit}/top.json?t=week&limit=15`;
  try {
    const raw = await fetchUrl(url);
    return JSON.parse(raw);
  } catch (err) {
    console.error(`Reddit fetch failed for r/${subreddit}:`, err.message);
    return null;
  }
}

async function main() {
  const slug = process.argv[2];
  if (!slug) {
    console.error('Usage: node fetch-content.js <industry-slug>');
    process.exit(1);
  }

  const userIndustryPath = path.join(HOME, '.follow-leaders', 'industries', `${slug}.json`);
  const bundledIndustryPath = path.join(SKILL_DIR, 'industries', `${slug}.json`);
  const industryPath = fs.existsSync(userIndustryPath)
    ? userIndustryPath
    : bundledIndustryPath;
  if (!fs.existsSync(industryPath)) {
    console.error(
      `No industry file found for "${slug}". Expected ${userIndustryPath} or ${bundledIndustryPath}. Set it up via SKILL.md first.`
    );
    process.exit(1);
  }
  const industry = JSON.parse(fs.readFileSync(industryPath, 'utf8'));

  fs.mkdirSync(STATE_DIR, { recursive: true });

  const result = {
    industry: industry.industry,
    slug: industry.slug,
    fetchedAt: new Date().toISOString(),
    podcasts: [],
    reddit: [],
    // Agent resolves via Composio or web_search/web_fetch (no free stable API).
    xAccountsToSearch: industry.xAccounts || [],
    linkedInProfilesToSearch: industry.linkedInProfiles || [],
    instagramAccountsToSearch: industry.instagramAccounts || [],
    tiktokAccountsToSearch: industry.tiktokAccounts || [],
    facebookPagesToSearch: industry.facebookPages || [],
    blogsToFetch: industry.blogs || [],
    newslettersToFetch: industry.newsletters || [],
  };

  for (const podcast of industry.podcasts || []) {
    const feedXml = await fetchYoutubeFeed(podcast.youtubeChannelId);
    result.podcasts.push({
      name: podcast.name,
      youtubeUrl: podcast.youtubeUrl,
      rawFeedXml: feedXml, // agent parses entries + reads transcripts/descriptions
    });
  }

  for (const sub of industry.subreddits || []) {
    const listing = await fetchRedditTop(sub);
    result.reddit.push({ subreddit: sub, listing });
  }

  const outPath = path.join(STATE_DIR, `${slug}-raw.json`);
  fs.writeFileSync(outPath, JSON.stringify(result, null, 2));
  console.log(`Wrote raw content to ${outPath}`);
}

main();
