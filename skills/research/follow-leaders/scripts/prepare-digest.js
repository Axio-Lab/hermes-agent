#!/usr/bin/env node
/**
 * prepare-digest.js
 *
 * Reads the raw content written by fetch-content.js, strips already-seen items
 * (state-based dedupe, same idea as the original skill's state-feed.json),
 * lightly normalizes the YouTube RSS XML into a plain list of new episodes, and
 * writes a single "ready to remix" JSON blob that an LLM (the agent running this
 * skill) turns into the final digest using the prompts/ files.
 *
 * This script deliberately does NOT call an LLM itself — remixing is the calling
 * agent's job, using prompts/digest-intro.md + summarize-*.md. This script's only
 * responsibility is: fetch raw -> dedupe -> hand off clean structured data.
 *
 * Usage:
 *   node prepare-digest.js <industry-slug>
 *
 * Output:
 *   Prints JSON to stdout: { newPodcastEpisodes, newRedditThreads, xAccountsToSearch }
 */

const fs = require('fs');
const path = require('path');
const os = require('os');

const HOME = os.homedir();
const STATE_DIR = path.join(HOME, '.follow-leaders', 'state');

function parseYoutubeEntries(xml) {
  if (!xml) return [];
  const entries = [];
  const entryBlocks = xml.split('<entry>').slice(1);
  for (const block of entryBlocks) {
    const videoId = (block.match(/<yt:videoId>(.*?)<\/yt:videoId>/) || [])[1];
    const title = (block.match(/<title>(.*?)<\/title>/) || [])[1];
    const published = (block.match(/<published>(.*?)<\/published>/) || [])[1];
    if (videoId) {
      entries.push({
        videoId,
        title,
        published,
        url: `https://www.youtube.com/watch?v=${videoId}`,
      });
    }
  }
  return entries;
}

function loadSeen(slug) {
  const p = path.join(STATE_DIR, `${slug}-seen.json`);
  if (fs.existsSync(p)) {
    return JSON.parse(fs.readFileSync(p, 'utf8'));
  }
  return { videoIds: [], redditIds: [] };
}

function saveSeen(slug, seen) {
  const p = path.join(STATE_DIR, `${slug}-seen.json`);
  fs.writeFileSync(p, JSON.stringify(seen, null, 2));
}

function main() {
  const slug = process.argv[2];
  if (!slug) {
    console.error('Usage: node prepare-digest.js <industry-slug>');
    process.exit(1);
  }

  const rawPath = path.join(STATE_DIR, `${slug}-raw.json`);
  if (!fs.existsSync(rawPath)) {
    console.error(`No raw content found at ${rawPath}. Run fetch-content.js first.`);
    process.exit(1);
  }
  const raw = JSON.parse(fs.readFileSync(rawPath, 'utf8'));
  const seen = loadSeen(slug);

  const newPodcastEpisodes = [];
  for (const podcast of raw.podcasts) {
    const entries = parseYoutubeEntries(podcast.rawFeedXml);
    for (const entry of entries) {
      if (!seen.videoIds.includes(entry.videoId)) {
        newPodcastEpisodes.push({ show: podcast.name, ...entry });
        seen.videoIds.push(entry.videoId);
      }
    }
  }

  const newRedditThreads = [];
  for (const r of raw.reddit) {
    const children = (r.listing && r.listing.data && r.listing.data.children) || [];
    for (const child of children) {
      const post = child.data;
      if (!post || !post.id) continue;
      if (!seen.redditIds.includes(post.id)) {
        newRedditThreads.push({
          subreddit: r.subreddit,
          title: post.title,
          url: `https://www.reddit.com${post.permalink}`,
          score: post.score,
          numComments: post.num_comments,
        });
        seen.redditIds.push(post.id);
      }
    }
  }

  // Cap seen-list growth so state files don't grow unbounded.
  seen.videoIds = seen.videoIds.slice(-500);
  seen.redditIds = seen.redditIds.slice(-500);
  saveSeen(slug, seen);

  const output = {
    industry: raw.industry,
    slug: raw.slug,
    preparedAt: new Date().toISOString(),
    newPodcastEpisodes,
    newRedditThreads,
    xAccountsToSearch: raw.xAccountsToSearch,
    linkedInProfilesToSearch: raw.linkedInProfilesToSearch || [],
    instagramAccountsToSearch: raw.instagramAccountsToSearch || [],
    tiktokAccountsToSearch: raw.tiktokAccountsToSearch || [],
    facebookPagesToSearch: raw.facebookPagesToSearch || [],
    blogsToFetch: raw.blogsToFetch || [],
    newslettersToFetch: raw.newslettersToFetch || [],
  };

  console.log(JSON.stringify(output, null, 2));
}

main();
