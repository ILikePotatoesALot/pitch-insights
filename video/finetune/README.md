# Fine-tuning the detector on a GPU machine (Windows, PowerShell)

This file contains the reproducible training procedure. Machine-specific assistant briefs are kept locally and excluded from Git.

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

You need a GPU with 8 GB or more of video memory (16 GB or more is comfortable) and Python 3.12. The tested configuration uses **AMD (ROCm on
Windows 11)**; an NVIDIA machine works too, so both routes are below.

```powershell
git clone https://github.com/ILikePotatoesALot/pitch-insights.git     # private: sign in to GitHub when asked
cd pitch-insights
git checkout video-path       # the branch has to be pushed to GitHub first
git checkout -b video-finetune-results   # all work and results go on this branch, not on video-path
py -3.12 -m venv video\.venv
video\.venv\Scripts\python -m pip install --upgrade pip
```

Install PyTorch **before** `requirements.txt`, from one of these two routes. Install every PyTorch package in one command
(a later `pip install torch...` or `torchvision` on its own can swap in the CPU build from PyPI).

**AMD, ROCm on Windows (tested configuration).** AMD's official wheels: PyTorch 2.9.1 with ROCm 7.2.1, Windows 11, Python 3.12 only.
Supported cards on AMD's matrix at the time of writing: Radeon RX 9070 / 9070 XT / 9060 XT, AI PRO R9700, RX 7900 XTX,
PRO W7900, RX 7700. Check [the compatibility matrix](https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/compatibility/compatibilityrad/windows/windows_compatibility.html)
for the card, and install the graphics driver AMD names for the release (26.2.2 for 7.2.1; use
[AMD's install page](https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/install/installrad/windows/install-pytorch.html)
if it has moved on, and use the commands on it). Both steps run inside the venv:

```powershell
video\.venv\Scripts\pip install --no-cache-dir `
    https://repo.radeon.com/rocm/windows/rocm-rel-7.2.1/rocm_sdk_core-7.2.1-py3-none-win_amd64.whl `
    https://repo.radeon.com/rocm/windows/rocm-rel-7.2.1/rocm_sdk_devel-7.2.1-py3-none-win_amd64.whl `
    https://repo.radeon.com/rocm/windows/rocm-rel-7.2.1/rocm_sdk_libraries_custom-7.2.1-py3-none-win_amd64.whl `
    https://repo.radeon.com/rocm/windows/rocm-rel-7.2.1/rocm-7.2.1.tar.gz

video\.venv\Scripts\pip install --no-cache-dir `
    https://repo.radeon.com/rocm/windows/rocm-rel-7.2.1/torch-2.9.1%2Brocm7.2.1-cp312-cp312-win_amd64.whl `
    https://repo.radeon.com/rocm/windows/rocm-rel-7.2.1/torchaudio-2.9.1%2Brocm7.2.1-cp312-cp312-win_amd64.whl `
    https://repo.radeon.com/rocm/windows/rocm-rel-7.2.1/torchvision-0.24.1%2Brocm7.2.1-cp312-cp312-win_amd64.whl
```

The second command takes several minutes. (`torchaudio` isn't used by this project; AMD installs it with the others, and it keeps
the three versions consistent.) ROCm builds of PyTorch answer through the same `torch.cuda` calls, so `torch.cuda.is_available()` is
`True` on a working AMD setup. `nvidia-smi` doesn't exist here; use the Task Manager's GPU tab or `torch.cuda.get_device_name(0)`.

**NVIDIA.** A current driver (`nvidia-smi` lists the card), then the command from https://pytorch.org/get-started/locally/
(Stable, Windows, Pip, Python, and the newest CUDA your driver supports).

The AMD route above was run on 22 Oct on a Radeon RX 9070 XT (ROCm 7.2.1). Installing the requirements afterwards kept that torch
(check with `pip install --dry-run -r video\requirements.txt` first). Then, for either route:

```powershell
video\.venv\Scripts\pip install -r video\requirements.txt
video\.venv\Scripts\python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"   # for AMD: 2.9.1+rocm7.2.1 True and the Radeon's name
```

If the version shown has no `+rocm` (AMD) or `+cu` (NVIDIA), `requirements.txt` replaced the GPU build with the CPU one:
see "If something goes wrong".

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

The files record the device they ran on (`detections.meta.json`, copied into the benchmark), so a baseline made on the AMD card says so.

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

Then the real run (3,328 training tiles and 800 for validation and test; the build takes under a minute, training about 23 minutes on an RX 9070 XT):

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

The weights are about 127 MB: copy `checkpoint_best_total.pth` (and `train_summary.json`) by USB or a share. The small result files
are in git, so use a separate branch on the GPU machine and push when authorised by the maintainer:

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
- **`torch.cuda.is_available()` is False:** a CPU build of PyTorch was installed (the version has no `+rocm` or `+cu`).
  Uninstall `torch torchvision torchaudio`, then install the GPU wheels again, all in one command (AMD: the second `pip install`
  in step 1; NVIDIA: the pytorch.org command), then re-run `pip install -r video\requirements.txt`.
- **AMD: still False with the `+rocm` build:** the card or driver isn't on AMD's Windows list for this release (check the
  compatibility matrix and the driver version), or the ROCm SDK wheels (first command) weren't installed in the same venv.
  Report the card, driver and the output of `python -m torch.utils.collect_env`; don't try other ROCm releases or Linux without the maintainer's say.
- **AMD: a HIP or "no kernel image" error during training, or training far slower than expected:** ROCm on Windows is a newer
  route than CUDA and this model hasn't been run on it. Try `--batch-size 2 --grad-accum 8` once; if it still fails, stop and report the error
  text. The fallback is a cloud or NVIDIA GPU (the maintainer's decision), not CPU training.
- **Hugging Face says 401 or 403:** the token is wrong or the account hasn't accepted the dataset's terms
  (open the dataset page on huggingface.co while signed in).
- **AMD (ROCm on Windows): `detect.py` or `eval_boxes.py` doesn't return after finishing.** A process that has run the detector
  on frames decoded from the video hangs at exit, after its output is written, and can't be killed for a while (training isn't
  affected). Wait for its last line (`500/500 frames ...`, or `wrote ...`), then stop it and go on; the output is complete.
  The stuck process holds no GPU memory and goes away by itself, or at a reboot.
- **Weights fail to download:** RF-DETR fetches its COCO weights (368 MB) on first use, so the machine needs internet access.
