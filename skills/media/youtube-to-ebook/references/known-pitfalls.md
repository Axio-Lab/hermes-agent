# Known Pitfalls

## YouTube Shorts detection

Filtering by duration alone fails — some Shorts exceed 60 seconds. Check whether the `/shorts/` URL resolves:

```python
def is_youtube_short(video_id):
    shorts_url = f"https://www.youtube.com/shorts/{video_id}"
    response = requests.head(shorts_url, allow_redirects=True, timeout=5)
    return "/shorts/" in response.url
```

## Chronological channel order

YouTube Search API is not reliably chronological. Use each channel's uploads playlist via `playlistItems`:

```python
channel_info = youtube.channels().list(part="contentDetails", forHandle=handle).execute()
uploads_playlist_id = channel_info["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
youtube.playlistItems().list(part="snippet", playlistId=uploads_playlist_id, maxResults=15).execute()
```

## Transcript API syntax

`YouTubeTranscriptApi.get_transcript()` is deprecated. Use the instance API:

```python
from youtube_transcript_api import YouTubeTranscriptApi

ytt_api = YouTubeTranscriptApi()
transcript = ytt_api.fetch(video_id)
```

Prefer the bundled `youtube-content` helper when fetching a single video transcript in Verxio.

## Transcript rate limits

Add ~2 seconds between transcript fetches when processing many videos.

## Name and term accuracy

Include video title and description in the writing prompt — descriptions usually contain correct spellings for people, companies, and jargon.

## Cloud automation blocked

YouTube often blocks transcript fetching from cloud CI hosts. Run scheduled jobs on the user's machine (launchd/cron), not GitHub Actions.

## Article truncation

If generated articles cut off mid-sentence, increase output length in the writing step or split very long transcripts across multiple article passes.
