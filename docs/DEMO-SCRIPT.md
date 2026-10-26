# Demo video: script and walkthrough

Drafted 26 Oct 2026 from the official rules (sections 4.1, 4.4, 4.7, 4.8, 4.9 and 6), the state of `main` at `5de5d9b` and the live app. The video is the one thing judges are sure to watch, and the rules say they need not watch past two minutes, so this plan runs **1:50**.

Live app: https://blue-moss-06018420f.1.azurestaticapps.net · Repo: https://github.com/ILikePotatoesALot/pitch-insights

## What the video has to do

**Rules that decide whether it counts** (section 4.4):

- Under 2:00 (aim for 1:50; a spare 10 seconds is deliberate).
- Shows the project running on the platform it was built for: a browser on the **live Azure address**. Keep the address bar visible at least once.
- A public URL on YouTube, Vimeo, Facebook Video or Youku, pasted into the project page on the hackathon site.
- No third-party trademarks and no copyrighted music. **No music at all.** No Premier League crest or name, no club crests, no real player names.
- English (the captions and voiceover; the Spanish and German on screen is fine, since the narration says what it is).

**What judges score** (section 6.2, 20% each) and where this script answers it:

| Criterion | What the rubric asks | Where the video answers it |
|---|---|---|
| Technological implementation | Creative, optimised synthetic data; quality practices; effective use of Foundry, Agent Framework and Azure services; well-structured code | Segment 2 ("checked against real football ranges"), segment 3 (the services named as they appear on screen), segment 6 (GitHub Actions deploys, 400+ tests, the README's technologies table) |
| Agentic design and innovation | Creative agent patterns; orchestration and multi-agent collaboration; novel AI that improves on existing approaches | Segment 3: four agents with distinct jobs, one shared evidence pack, checks, retry and fallback. Segment 5: the same agents on video |
| Real-world impact | A significant problem; deployable in production; impact on users | Segment 1 ("studios, streamers and fans in any market"), segment 5 (auto-eventing on real footage), segment 6 (running on Azure, free to try) |
| User experience and presentation | Intuitive design; the video communicates the value; balanced front end and back end | The whole video: the 3D pitch, overlays and two-viewer view (front end) against agents, checks and Azure (back end) |
| Adherence to category | Matches the category's description | Segment 3 is written to the **Best Multi-Agent System** wording: "distinct roles", "shared state and effective handoffs", "recover from failures", "an outcome a single agent couldn't". Pick that category on the form; Foundry is the backup |

Stage one of judging is pass or fail on fitting the theme and using the required technologies, so the first 35 seconds name the five pipeline stages and a Microsoft technology.

**The five stages (rules 4.1(i)) the video must visibly hit:** Ingest, Interpret, Explain, Render, Personalize. Segments 2 to 4 do. The real-footage segment answers the rules' own "auto-eventing" idea (a model over video generating the events).

## Before you record

- Use a **1920 × 1080** browser window at 100% zoom, bookmarks bar hidden, notifications off (Windows Focus assist), no other tabs visible, a private window so no extensions show.
- Appearance: the app starts **Light**; keep it. Light text stays readable after YouTube's compression.
- Open https://blue-moss-06018420f.1.azurestaticapps.net a couple of minutes ahead so the server is awake (DEPLOY.md keeps one replica warm, so it should be).
- Tools: Xbox Game Bar (Win+G) or OBS to capture the screen; Clipchamp (built into Windows, no music needed) to cut, caption and add the end card. Record the **screen and the voice separately** and join them in the editor. Live narration while clicking is where takes go wrong.
- Rehearse once with a stopwatch. Speaking pace used here: about 2.3 words a second.
- Use the links below so no profile picker appears. Each is a normal link; open it in a fresh tab for each take.

## Shot list

Times are the target in the finished video. "Say" is the voiceover (full text in one block further down).

### 1. Hook: one match, two fans (0:00 to 0:15)

- **Open:** https://blue-moss-06018420f.1.azurestaticapps.net/?compare=1 (reload it just before you press record so the match starts from kick-off).
- **On screen:** two panes of the same match: a Potato FC fan, casual, in German, beside a Carrot FC analyst in English. The goal at 1' arrives within seconds: both commentary lines appear, one German, one English with the numbers.
- **Edit:** zoom for two seconds on the two commentary lines. Caption: *Same match, two viewers*.
- **Say:** "Football stories don't end at the scoreline. Seize the game turns match events into explainable intelligence, for studios, streamers and fans in any market. Here, one match reaches two fans in two different ways."

### 2. The pipeline: ingest, interpret, explain (0:15 to 0:35)

- **Open:** `/?match=comeback-POT-CAR&team=POT&player=POT-11&mode=analyst&lang=en&layout=fan&speed=20`
- **Do:** type **87** in "Jump to" and press Go. At 88' Carrot's late equaliser (2–2) arrives: the win-probability bar swings, ratings move, a new card lands in Key moments. Click **Why?** on that card and hold three seconds on the evidence.
- **Captions** appear one by one as each word is said: *Ingest · Interpret · Explain · Render · Personalize*.
- **Say:** "Under the hood is one pipeline: ingest, interpret, explain, render, personalise. Synthetic matches, checked against real football ranges, stream in event by event. Code works out the stats, xG, win probability and live ratings. Then agents explain why a moment mattered, and Why shows the evidence."

### 3. The agents (0:35 to 1:02): the Multi-Agent segment

- **First half (0:35 to 0:47):** the README's architecture diagram on GitHub (scroll to "Architecture"; the repo is private until you publish it, which is fine while you're signed in). Hold on the agents box.
- **Second half (0:47 to 1:02):** back in the app, open `/?match=comeback-POT-CAR&team=POT&player=POT-11&mode=analyst&lang=es&layout=fan&speed=20`, jump to 87, click **Why?** on the 88' card. Zoom on the small line under the commentary. It reads, in the app's own words, that an agent wrote it, how many names and numbers were checked against the facts, that Azure AI Content Safety screened it and that Azure AI Translator translated it.
- **Captions:** *Microsoft Agent Framework · Foundry GPT-4o* over the diagram; *Content Safety · Foundry groundedness · Translator* over the zoom.
- **Say:** "Four agents on Microsoft Agent Framework and Foundry GPT-4o share one evidence pack per moment. Memory recalls similar moments. Explainer and Narrator write casual and analyst voices. A Video Narrator covers real footage. Every line is checked against the evidence, retried once, then falls back to a plain headline. Azure Content Safety screens it, Foundry scores it, and Azure Translator translates it."

### 4. Personalise and the Overlay Director (1:02 to 1:16)

- **Open:** `/?match=comeback-POT-CAR&team=POT&player=POT-11&mode=casual&lang=es&layout=broadcast&speed=20`
- **On screen:** Broadcast layout. The goal at 1' brings a lower-third and the spotlight on #11 (the favourite player). At about 1:10 click **Analyst**, then change the language to English: the commentary changes in place.
- **Caption:** *Favourite player · 6 languages · casual or analyst*.
- **Say:** "Each viewer makes it their own: a favourite player with a spotlight that follows them, six languages, casual or analyst. An Overlay Director schedules the graphics, so the screen never clutters."

### 5. Real footage: auto-eventing (1:16 to 1:33)

- **Open:** `/?match=117093-38min_ft&follow=L-t11&speed=5` (starts at 38:00 and plays the whole 100 s in 20 seconds; the moments appear at 38:02, 38:32, 38:41, 38:48 and 39:30).
- **On screen:** tracked players on the 3D pitch, the starred "Left #11" followed by the spotlight, possession and the Players list filling in, key moments in hedged words ("appears to", "seems to"). At about 1:28 click another row in Players to switch who is followed.
- **Caption, for the whole segment** (this is the licence's credit): *Real footage: SoccerTrack v2 (CC BY 4.0). Labels are tracker IDs, not player identities.*
- **Say:** "The same pipeline reads real footage. A fine-tuned RF-DETR detector tracks players from licensed match video, and the Video Narrator hedges whatever the model wasn't sure of. Follow any tracked player. Ninety-seven percent precision, credited to SoccerTrack v2."
- Possession reads 100% for the first seconds because only the left side has had the ball; don't linger on it.
- Optional, if you have room: the last moment (39:30) shows "first draft corrected", the retry catching an unhedged sentence. It's the best on-screen proof of "recovers from failures".

### 6. On Azure, ready to try (1:33 to 1:50)

- **On screen:** 1:33 to 1:38 the README's "Microsoft and Azure technologies" table; 1:38 to 1:43 the repo's **Actions** tab with green "Deploy backend" and "Deploy frontend" runs (it shows the deploys come from GitHub Actions); then a plain end card for 7 seconds.
- **End card text:** *Seize the game* · the live address · the repo address · *Synthetic data, fictional clubs. Real footage: SoccerTrack v2 (CC BY 4.0).*
- **Say:** "It runs live on Azure, deployed from GitHub Actions, with over four hundred automated tests. Try it free at the link below." Then stay silent on the end card.

## The voiceover in one block (233 words, about 100 seconds spoken)

> Football stories don't end at the scoreline. Seize the game turns match events into explainable intelligence, for studios, streamers and fans in any market. Here, one match reaches two fans in two different ways.
>
> Under the hood is one pipeline: ingest, interpret, explain, render, personalise. Synthetic matches, checked against real football ranges, stream in event by event. Code works out the stats, xG, win probability and live ratings. Then agents explain why a moment mattered, and Why shows the evidence.
>
> Four agents on Microsoft Agent Framework and Foundry GPT-4o share one evidence pack per moment. Memory recalls similar moments. Explainer and Narrator write casual and analyst voices. A Video Narrator covers real footage. Every line is checked against the evidence, retried once, then falls back to a plain headline. Azure Content Safety screens it, Foundry scores it, and Azure Translator translates it.
>
> Each viewer makes it their own: a favourite player with a spotlight that follows them, six languages, casual or analyst. An Overlay Director schedules the graphics, so the screen never clutters.
>
> The same pipeline reads real footage. A fine-tuned RF-DETR detector tracks players from licensed match video, and the Video Narrator hedges whatever the model wasn't sure of. Follow any tracked player. Ninety-seven percent precision, credited to SoccerTrack v2.
>
> It runs live on Azure, deployed from GitHub Actions, with over four hundred automated tests. Try it free at the link below.

## If it runs over two minutes, cut in this order

1. The Actions tab in segment 6 (keep the README table and the end card).
2. The click that switches who is followed in segment 5.
3. The language switch at the end of segment 4.
4. The sentence "Memory recalls similar moments." (the app doesn't show Memory on screen).
5. Never cut: the five stage names, the Why? evidence, the check line, the hedged real-footage commentary, the end card.

## Say it accurately

These are the lines judges could fact-check; each is true as written.

- Say "streams in event by event", not "live match feed": the matches are synthetic and replayed at match speed. Nothing looks ahead, so a live feed would behave the same (tests cover it).
- The agents write ahead of time and the checked commentary is stored, so the app never waits on a model. If you mention it, call it a choice for broadcast reliability.
- The clip is **real footage but not identified players**: "Left #11" is a tracker ID. It has no score and no goals; don't say a goal happens in it.
- "97% precision" is on this one 100-second clip (the settings were tuned on it). Don't say it generalises.
- Don't show or say Premier League, a club crest or a real player's name. Don't add a music bed. The Windows, browser and GitHub interface showing on screen is fine.
- Fictional clubs and players are fine and worth a half-second: the end card says so.

## Record, edit, upload

1. Record each segment's screen take separately, two takes each, 5 to 10 seconds longer than needed.
2. Record the voiceover in one quiet take from the block above (phone voice recorder or Clipchamp's recorder). Leave a half-second gap between paragraphs so you can cut to the segments.
3. In Clipchamp: lay the voiceover first, cut the screen takes to it, add the captions above as text overlays, turn on auto-captions as burned-in subtitles (judges may watch muted), add the end card. Export **1080p**.
4. Check the final length is **under 1:55** on the timeline.
5. Upload to YouTube as **Public** (Unlisted works as a link, but public can't fail). Title: *Seize the game: explainable, personalised football intelligence (Microsoft Premier League Hackathon)*. Put the live address and repo in the description. Open the link in a private window to confirm it plays.
6. Add the video link in three places: the README line "Demo video: *(link added at submission)*", the header of [SUBMISSION.md](SUBMISSION.md), and the project page on the hackathon site (the rules ask for the public URL there).

## State of the project when this was written (26 Oct, evening)

- `main` is `5de5d9b`; no open pull requests. Codex merged #23 to #25 (the player-following fix and submission refresh, mobile and light/dark appearance, the rename to "Seize the game"). The latest backend and frontend deploys both succeeded and the live site shows the new name.
- Tests: 418 backend (collected here) and 12 frontend (run here, all pass).
- **The repo is still private.** It must be public before submitting (rule 4.4).
- The README's architecture diagram still lists the agents as "Memory, Explainer, Narrator"; the Video Narrator is missing from the picture (the text is right). Fix that one label before you film the diagram in segment 3, or say "four agents" over the table instead.
- Still open from the checklist: the video and its link, fitting SUBMISSION.md to the form's fields, making the repo public, submitting by **27 Oct, 11:59 pm Pacific** (about 2:59 pm on 28 Oct in Singapore), and the Azure clean-up after 10 Nov.
