# Continuous simulation prototype

Branch: `codex/continuous-match-simulation`.

Choose the `continuous` match, or open the local frontend with
`?match=continuous-prototype&team=POT&player=POT-07&mode=analyst&speed=1`.
Start the backend and frontend normally. No sample generation command or model credentials are required.

This is a six-minute first-half exhibition with the existing Potato and Carrot
squads. It is a separate experimental match; the existing synthetic samples and
real-footage clip remain available.

## Behaviour

- All 22 players have persistent positions and velocities, updated every 0.2 seconds.
- Role, formation, team style, possession and the ball determine movement targets.
- Players accelerate towards those targets with a pace-dependent speed limit.
- The carrier chooses between running, passing and shooting using current positions.
- Pass selection considers forward progress, available space and defenders in the passing lane.
- The ball travels independently during a pass. Completion requires player contact;
  opponents can intercept. A tackle requires a defender within one metre of the ball.
- Shots use location, pressure and shooting ability. Their outcome event appears at
  the end of the ball's flight. Outcomes remain probabilistic.
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
- Pause, speed, minute seeking, replay and comparison work with the new feed.

The seeded simulation generates ahead of playback and is cached in process.
Clients receive only frames and events due on their replay clock. This mirrors
the preprocessed footage replay; it is not a live external tracking feed.

## Current limits

This is a demonstration of continuous movement and shared event evidence, not a
calibrated football model. The six minutes are intentionally busy. All shot
outcomes currently use a simplified return to the centre, including saved and
off-target shots. No offside, fouls, cards, substitutions, set-piece rules,
player collision physics or second half are implemented. Goalkeepers have basic
positioning; save outcomes are probabilistic rather than a reach model.

The existing ratings and win probabilities were designed for full matches. They
are illustrative here. No stored AI narration or translations have been generated
for this new match. The positional activity surface builds from the point the
viewer starts or seeks to, up to its normal two-minute window.

Further work should tune movement and event rates, add lawful restarts and
goalkeeper behaviour, then expand to a full match with period changes and squad
changes. Tracking-derived tactical explanations can follow once the simulation
is convincing enough to support them.

## Validation

Backend coverage checks deterministic generation, 22 persistent identities,
movement limits, pass reception, tackle contact, event schema and intelligence
compatibility, paused exact-time seeking, listing and end-of-replay handling.
Frontend coverage includes selecting and following simulated players without
action events, terrain interpolation and pause behaviour, shot peaks and goal
glow, slope sampling, switching between surface views, movement gaps and identity
jumps, nearby-player filtering, overlay toggles and playback clock alignment,
plus the existing player following and replay regression tests.
