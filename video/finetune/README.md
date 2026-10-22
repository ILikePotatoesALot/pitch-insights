# Fine-tuning the detector on a GPU machine (Windows, PowerShell)

If a coding assistant (for example Claude Code) is doing this for you, point it at [LLM_BRIEF.md](LLM_BRIEF.md): it has the
rules, the stop conditions and what to report. This file is the procedure.

Fine-tunes RF-DETR small on SoccerTrack's own tight boxes, then scores it against the pre-trained model on
frames it never saw, and re-runs the video pipeline on the benchmark clip. Design and reasons:
[docs/DESIGN.md, Video path](../../docs/DESIGN.md#video-path). A GPU also makes the baseline detection fast
(minutes, not an hour), so these steps refresh the stored benchmark too.

**What it does and doesn't do**
- Training labels are SoccerTrack's MOT boxes: 22 players and goalkeepers a frame for the first four minutes of
  the half, 5,976 frames. Training uses 450 of them; validation and test are separate stretches with 8-second gaps.
  The benchmark clip (38:00-39:40) is never trained on.
- People the file doesn't box (spectators, referees, staff) become background, so the model should learn to
  ignore them. Expect the gain in **precision**; recall is already about 98% at IoU 0.5.
- The labels have no ball, so the ball still comes from the pre-trained model.

## 1. Set up the machine (once)

You need an NVIDIA GPU with 8 GB or more of video memory and a current driver. In PowerShell, `nvidia-smi` should list the card.

```powershell
git clone https://github.com/ILikePotatoesALot/pitch-insights.git     # private: sign in to GitHub when asked
cd pitch-insights
git checkout video-path       # the branch has to be pushed to GitHub first
git checkout -b video-finetune-results   # all work and results go on this branch, not on video-path
py -3.12 -m venv video\.venv
video\.venv\Scripts\python -m pip install --upgrade pip
```

Install PyTorch with CUDA first, using the command from https://pytorch.org/get-started/locally/ (Stable, Windows,
Pip, Python, and the newest CUDA your driver supports). Then:

```powershell
video\.venv\Scripts\pip install -r video\requirements.txt
video\.venv\Scripts\python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"   # True and your GPU
```

Create `.env` in the repo root (it is ignored by git; never commit it) with your Hugging Face read token. The dataset is gated,
so the account must have accepted the SoccerTrack v2 terms:

```
HF_TOKEN=hf_xxxxxxxx
```

## 2. Get the data (about 6 GB)

```powershell
video\.venv\Scripts\python video\finetune\fetch_data.py
video\.venv\Scripts\python video\extract_gsr.py          # about 30 s: ground truth for the clip
```

## 3. Baseline on the GPU (pre-trained model; refreshes the stored benchmark)

```powershell
video\.venv\Scripts\python video\detect.py calib
video\.venv\Scripts\python video\calibrate.py
video\.venv\Scripts\python video\detect.py clip
video\.venv\Scripts\python video\process.py
```

## 4. Fine-tune

First check that training runs at all (a few frames, one epoch, a minute or two):

```powershell
video\.venv\Scripts\python video\finetune\build_dataset.py --limit 3 --out data\finetune\smoke
video\.venv\Scripts\python video\finetune\train.py --smoke --dataset data\finetune\smoke
```

Then the real run (about 3,900 training tiles and 800 for validation and test; the build takes a few minutes):

```powershell
video\.venv\Scripts\python video\finetune\build_dataset.py
video\.venv\Scripts\python video\finetune\train.py
```

If it stops with "out of memory", lower the batch and raise accumulation, for example `--batch-size 4 --grad-accum 4`.
Training stops early when the validation score stops improving. The checkpoints and `train_summary.json` land in
`data\finetune\runs\<name>\`; the best one is `checkpoint_best_total.pth` (the summary lists the files).

## 5. Compare

Box-level, on the held-out test frames (pre-trained against fine-tuned, written to `samples\video\117093-boxes.eval.json`):

```powershell
video\.venv\Scripts\python video\finetune\eval_boxes.py --weights data\finetune\runs\<name>\checkpoint_best_total.pth
```

Then the whole pipeline on the benchmark clip with the new weights. `VIDEO_TAG` keeps every file of this run next to the baseline's:

```powershell
$env:VIDEO_TAG = "_ft"
$w = "data\finetune\runs\<name>\checkpoint_best_total.pth"
video\.venv\Scripts\python video\detect.py calib --weights $w
video\.venv\Scripts\python video\calibrate.py
video\.venv\Scripts\python video\detect.py clip --weights $w
video\.venv\Scripts\python video\process.py
video\.venv\Scripts\python video\preview.py        # optional: data\video\117093\preview.mp4
Remove-Item Env:VIDEO_TAG
```

`samples\video\117093-38min_ft.benchmark.json` is then comparable with `117093-38min.benchmark.json`.

## 6. Bring the results back

The weights are about 370 MB: copy `checkpoint_best_total.pth` (and `train_summary.json`) by USB or a share. The small result files
are in git, so on the GPU machine (push only when Austin says so; an assistant works on that branch from the start, see the brief):

```powershell
git add samples/video
git commit -m "Fine-tuning results and refreshed baseline benchmark"
git push -u origin video-finetune-results
```

To log a run in the Azure ML workspace, put `MLFLOW_TRACKING_URI=...` in `.env` (from the portal: ML-pitch-insights >
Essentials) and run `video\.venv\Scripts\python video\log_mlflow.py` (with `VIDEO_TAG` set for the fine-tuned run). It opens a
browser sign-in.

## If something goes wrong

- **`cv2` fails to import after installing:** the training extras can pull in `opencv-python-headless` next to
  `opencv-python`. Run `video\.venv\Scripts\pip uninstall -y opencv-python opencv-python-headless`, then
  `video\.venv\Scripts\pip install opencv-python==5.0.0.93`.
- **`torch.cuda.is_available()` is False:** a CPU build of PyTorch was installed. Uninstall `torch torchvision` and install the CUDA
  build from pytorch.org, then re-run `pip install -r video\requirements.txt`.
- **Hugging Face says 401 or 403:** the token is wrong or the account hasn't accepted the dataset's terms
  (open the dataset page on huggingface.co while signed in).
- **Weights fail to download:** RF-DETR fetches its COCO weights (368 MB) on first use, so the machine needs internet access.
