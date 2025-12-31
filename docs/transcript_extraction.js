(async () => {
  const VIDEO_ID = "adOkTjIIDnk";

  // 1️⃣ Fetch video HTML
  const watchUrl = `https://www.youtube.com/watch?v=${VIDEO_ID}`;
  const html = await fetch(watchUrl).then(r => r.text());

  // 2️⃣ Extract INNERTUBE_API_KEY using regex (same as Python)
  const apiKeyMatch = html.match(/"INNERTUBE_API_KEY"\s*:\s*"([^"]+)"/);
  if (!apiKeyMatch) {
    console.error("INNERTUBE_API_KEY not found");
    return;
  }
  const apiKey = apiKeyMatch[1];
  console.log("API KEY:", apiKey);

  // 3️⃣ Call Innertube player API
  const innertubeUrl =
    `https://www.youtube.com/youtubei/v1/player?key=${apiKey}`;

  const innertubeResponse = await fetch(innertubeUrl, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      context: {
        client: {
          clientName: "WEB",
          clientVersion: "2.20241201.00.00"
        }
      },
      videoId: VIDEO_ID
    })
  }).then(r => r.json());

  // 4️⃣ Extract captions JSON
  const captions =
    innertubeResponse?.captions?.playerCaptionsTracklistRenderer?.captionTracks;

  if (!captions || captions.length === 0) {
    console.error("No captions available");
    return;
  }

  console.log("Available caption tracks:", captions);

  // 5️⃣ Pick first track (usually auto-generated English)
  const track = captions[0];
  console.log("Using track:", track.languageCode, track.kind);

  // 6️⃣ Fetch raw transcript XML
  const transcriptXml = await fetch(track.baseUrl).then(r => r.text());

  console.log("RAW TRANSCRIPT XML:");
  console.log(transcriptXml);

  return transcriptXml;
})();