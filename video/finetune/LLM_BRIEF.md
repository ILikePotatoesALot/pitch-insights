# Brief for the coding assistant on the GPU machine

You are a coding assistant (for example Claude Code) working for **Austin** on a Windows machine with an NVIDIA GPU.
Read this whole file first, then do the task. Austin is not watching every step, so follow the rules, stop at the
stop conditions, and report in the format at the end.

## The project and your task

**Pitch Insights** is Austin's entry to the Microsoft Premier League Hackathon (deadline 27 Oct 2026, 11:59 pm Pacific).
The **video path** turns real, licensed match footage (SoccerTrack v2, CC BY 4.0) into player positions and events, and is
scored against SoccerTrack's ground truth. It uses RF-DETR small as the detector. Your task is to **fine-tune that
detector on this machine's GPU, measure whether it beats the pre-trained model, and hand the results back.**

You are on the branch `video-path`. Everything you need is in `video/finetune/`:
[README.md](README.md) has the exact commands (it is the procedure; this file is the rules and the reporting).
Background and reasons are in [docs/DESIGN.md, Video path](../../docs/DESIGN.md#video-path) and
[docs/HANDOFF.md](../../docs/HANDOFF.md).

## Rules (all of them apply)

1. **Secrets.** The Hugging Face token lives in the repo-root `.env` (ignored by git) as `HF_TOKEN=...`. Never print it,
   echo it, log it, put it in a command line, or commit it. Never edit `.env.example` except to add empty placeholders.
   If a command output or error contains a token, redact it before you show it to anyone.
2. **Git.**
   - Work on a new branch `video-finetune-results` cut from `video-path`. **Do not commit to `main` or `video-path`,
     and never push to either.**
   - Commit locally as often as you like. **Push `video-finetune-results` only when Austin says so.**
   - Commit only small files: scripts, docs, and the JSON/JSONL results in `samples/video/`. **Never commit** anything in
     `data/`, model weights (`*.pth`, `*.pt`), video, or `.env`. They are git-ignored; do not force-add them.
3. **Installs.** Use only `video\.venv` (Python 3.12) and what `video\requirements.txt` lists, plus PyTorch with CUDA.
   Do not install anything else, and do not use the machine's default Python. If something else is needed, say what and
   why, and wait.
4. **Honest results.** Do not change the benchmark clip (`video/clip.py`: frames 57,001-59,500), the splits
   (`DEFAULT_SPLIT` in `backend/pitch_insights/video/mot.py`), the detection thresholds, or the calibration to make the
   numbers look better. Never train on the benchmark clip or the `test` frames. Choose settings on `valid`, not on `test`.
   Run at most **two** training configurations (for example the defaults, then one change such as a different epoch
   count or batch size), and report both, even if the second is better. If the fine-tuned model is worse, say so plainly.
5. **Labels.** Training labels are the MOT boxes from `build_dataset.py`. Do not use the GSR image boxes (all 43 px tall
   and loose) and do not use the model's own detections as labels.
6. **Data licence.** SoccerTrack v2 is CC BY 4.0: keep the credit wherever results are shown. Do not use any other footage.
   Never use the Roboflow or Bundesliga sample clips.
7. **Do not delete** `data/` contents or anything you did not create. `build_dataset.py --force` only replaces a folder it
   made itself; keep it that way.
8. **Language.** Plain British English in anything you write. Refer to Austin by name, not with pronouns.
9. **Long jobs** (training, detection) take minutes to an hour: run them so their output is saved to a file, and do not
   start the same job twice. Detection is resumable; if it stops, run the same command again.

## Stop conditions

Stop and report (do not loop or improvise) if:
- the smoke run (`train.py --smoke`) fails and the README's "If something goes wrong" section does not fix it within two
  attempts. Report the full error text (redacted) and what you tried;
- `torch.cuda.is_available()` is False after installing, or the GPU has less than 8 GB of memory;
- the Hugging Face download is refused (401/403) or the files do not match the sizes in the README (video about 3.35 GB,
  GSR about 2.7 GB);
- a script needs a change to run. You may make a **minimal** fix, but commit it on its own with a clear message, and list it
  in your report so Austin can bring it back into `video-path`;
- anything would require pushing, installing something unlisted, or changing the benchmark clip, splits or thresholds.

## What "done" looks like, and what to report

Follow `video/finetune/README.md` steps 1 to 5 (step 6, pushing, only when Austin says). Then report to Austin, in this order,
in plain language:

1. **Machine:** GPU name and memory, driver, Python and PyTorch versions.
2. **Smoke run:** whether it passed.
3. **Training:** the configuration(s) you ran, how long each took, the epoch it stopped at, and the checkpoint file used
   (`data\finetune\runs\<name>\checkpoint_best_total.pth`, plus its size).
4. **Box check** (`eval_boxes.py`, the table it printed, also saved in `samples/video/117093-boxes.eval.json`): precision and
   recall at IoU 0.5 and 0.75, raw and on pitch, for pre-trained and fine-tuned. State which is better and by how much.
   Reference, from two test frames on a CPU: pre-trained recall about 98% at IoU 0.5 (91% at 0.75), precision 43% raw and
   73% on pitch. The expected gain from fine-tuning is **precision** (it should learn to ignore spectators and officials)
   without losing recall.
5. **Pipeline benchmark on the clip** (`samples/video/117093-38min_ft.benchmark.json` against the refreshed
   `117093-38min.benchmark.json`): players found, precision, position error (mean and median), team accuracy, ID
   consistency, ball frames, events within 5 s. For reference, the CPU baseline before the tile-merge fix was: found 91%,
   precision 85%, position error 0.78 m mean and 0.59 m median, team 88%, ID consistency 72%, ball in 45% of frames, event
   precision 74% and recall 38% within 5 s. Say plainly if the refreshed baseline moved from those numbers.
6. **Recommendation:** use the fine-tuned model or not, in one sentence with the deciding number.
7. **Files:** the list of files to bring back (the weights file, `train_summary.json`, and the commits on
   `video-finetune-results`), and any script changes you made, with the commit hashes.

Keep the report short and factual. Do not claim anything you did not run.
