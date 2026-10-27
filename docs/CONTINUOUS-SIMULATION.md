# Continuous simulation prototype

Branch: `codex/continuous-match-simulation`.

Choose the `continuous` match, or open the local frontend with
`?match=continuous-prototype&team=POT&player=POT-07&mode=analyst&speed=1`.
Start the backend and frontend normally. No sample generation command or model credentials are required.

This is a six-minute first-half exhibition with the existing Potato and Carrot
squads. It is a separate experimental match; the existing synthetic samples and
real-footage clip remain available.

Restart positioning uses the basic procedures in [IFAB Law 8](https://www.theifab.com/laws/latest/the-start-and-restart-of-play/)
and [Law 16](https://www.theifab.com/laws/latest/the-goal-kick/). This prototype does
not implement a complete referee or all offences in those Laws.

## Behaviour

- All 22 players have persistent positions and velocities, updated every 0.2 seconds.
- Role, formation, team style, possession and the ball determine movement targets.
- Players accelerate towards those targets with a pace-dependent speed limit.
- The carrier chooses between running, passing and shooting using current positions.
- Defenders blend marking with their team shape. Teammates steer away from one
  another, and a pressured carrier can move laterally. Passing favours space and
  clear lanes, and shooting is a choice rather than automatic in the final third.
- Pass selection considers forward progress, available space and defenders in the passing lane.
- The ball travels independently during a pass. Completion requires player contact;
  opponents can intercept. A tackle requires a defender within one metre of the ball.
- Shots use location, pressure and shooting ability. Their outcome event appears at
  the end of the ball's flight. Outcomes remain probabilistic.
- Goals lead to a kick-off by the conceding team, with the ball returned to the
  centre and players clearing the correct halves and centre circle. Untouched
  misses over the goal line lead to a goal kick from the defending goal area.
  Saved shots leave the keeper holding the ball briefly before distributing;
  opponents cannot tackle it out of their hands. Restarts are passes to a teammate.
- Tracking frames and validated match events share one replay clock. Existing
  statistics, ratings and deterministic explanations consume the generated events.
- Terrain heights and colours interpolate on the same buffered clock as the
  players. Shot peaks rise and fade, with a brief glow for goals. Pausing holds
  the surface at the latest frame; seeking clears its old shape immediately.
- Player and ball ground height is interpolated across the terrain grid to avoid
  steps when crossing a slope.
- Current play is the default tracking view: current player positions, quickly
  fading movement and a local emphasis around the observed ball. Activity history
  retains the longer activity surface. Both accumulate while watching, so changing
  views also works while paused and does not reconnect the replay.
- Selecting a player reveals up to eight seconds of their observed movement and
  rings around players within twelve metres, in team colours. Each overlay can be
  switched off. Trails are cleared on seeking and break across missing detections,
  gaps over 0.6 seconds and position jumps faster than 11 m/s. They use the same
  buffered drawing time as the markers and never include future observations.
- Tap a marker or follow someone from the ratings list to inspect them without
  reconnecting. Return to favourite restores the profile's player.
- Pause, speed, second-level seeking, replay and comparison work with the new
  feed. Each known moment has a Watch this play button which starts five seconds
  before it. Rewinding rebuilds the feed from evidence available at that point.
- Camera choices include Full pitch, Follow ball and Follow player. Dragging or
  zooming takes over as Manual view. A missing ball or player holds the camera at
  its last focus; returning to Full pitch restores the fitted view.
- The Position insights panel measures outfield team width, depth, the defenders'
  median distance from their own goal line and players within five metres of the
  ball. Periodic moments identify off-ball advances of at least eight metres over
  four seconds, checking that the player did not hold the ball during that period.
- Analysts can enable Formation lines, off by default, for one selected team.
  The selection starts with the favourite club if it is playing, otherwise the
  home team. A selector switches sides. Lines connect outfield players across
  each observed depth band and follow the same interpolated positions as the
  markers, including the pitch's changing terrain height. Goalkeepers are excluded.
  The observed shape is estimated from two to four depth bands, without using
  the starting formation. Depth is smoothed over replay time and changed group
  membership must persist for 1.5 seconds before adoption. Lines are hidden during
  kick-offs and goal kicks, or when a team lacks all ten outfield observations.
  Pausing holds the geometry and regrouping clock; seeking clears previous groups.
  This is a geometric estimate, not a confirmed tactical formation.
- The exhibition has stored English commentary written by the Simulation narrator
  through Microsoft Agent Framework and Foundry. Its input contains event facts
  and these positional measurements. Names, numbers and selected unsupported
  intention phrases are checked; Azure AI Content Safety screens the output.
  English plus Spanish, French, German, Dutch and Simplified Chinese are available
  for moment headlines, evidence and commentary. Interface controls remain English;
  individual translations that fail name or number checks retain their English.
  Commentary is never generated during playback. To regenerate after changing
  the simulation, run `python backend/scripts/generate_commentary.py continuous-prototype`
  with the project's agents extra installed and its provider configured. Then run
  `python backend/scripts/translate_moments.py continuous-prototype` with Azure
  Translator configured. The translator uses the same generated evidence as playback
  without requiring a source JSONL file, and reuses unchanged translations.
- Prepared moments also pass through the Overlay Director, so the pitch's
  broadcast overlays use the same checked commentary as the moments feed.

The seeded simulation generates ahead of playback and is cached in process.
Clients receive only frames and events due on their replay clock. This mirrors
the preprocessed footage replay; it is not a live external tracking feed.

## Current limits

This is a demonstration of continuous movement and shared event evidence, not a
calibrated football model. Event rates are hand-tuned. No offside, fouls, cards,
substitutions, corners, throw-ins or second half are implemented. Kick-off and
goal-kick positioning is modelled, without a referee or countdown offences.
Player spacing is steering rather than collision physics. Goalkeepers have basic
positioning and distribution; save outcomes remain probabilistic rather than a
full reach model.

Ratings are labelled illustrative. Full-match win predictions and season-goal
increments are omitted from the exhibition and its commentary evidence. Shape and proximity figures
describe geometry; they do not prove pressing success or player intentions.
The positional activity surface builds from the point the viewer starts or seeks to and fades
over match time.

Further work should calibrate movement and event rates against match data, expand
the set-piece and goalkeeper models, then add a full match with period and squad
changes. The new narration's name-and-number checks do not establish that every
possible natural-language inference is supported, so the prompt and human review
remain important.

## Validation

Backend coverage checks deterministic generation, 22 persistent identities,
movement limits, pass reception, tackle contact, event schema and intelligence
compatibility, saved-ball protection, restart placement, measured positional
evidence, commentary routing, paused exact-time seeking, listing and end handling.
The replay coverage also checks that a goal's stored commentary reaches its
broadcast lower-third without an exhibition win prediction.
Frontend coverage includes selecting and following simulated players without
action events, terrain interpolation and pause behaviour, shot peaks and goal
glow, slope sampling, switching between surface views, movement gaps and identity
jumps, nearby-player filtering, overlay toggles and playback clock alignment,
camera focus and manual override, plus existing player following and replay
regression tests.
