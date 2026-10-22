"""Log the benchmark run to the Azure ML workspace through MLflow.

Follows Microsoft's "Configure MLflow for Azure Machine Learning": the
workspace's tracking URI in `MLFLOW_TRACKING_URI` (read from the repo-root
`.env`, never printed), `mlflow-skinny` plus the `azureml-mlflow` plugin, and
sign-in through azure-identity (Azure CLI, or a browser window the first time).
No compute is used, so no quota is needed.

Needs `mlflow-skinny` 3.15.0 and `azureml-mlflow` 1.62.0.post6 in video\\.venv
(installed 22 Oct). The first run opens a browser window to sign in.

    video\\.venv\\Scripts\\python video\\log_mlflow.py
"""

from __future__ import annotations

import json
import os

import clip

EXPERIMENT = "video-path-benchmark"


def tracking_uri() -> str | None:
    if os.environ.get("MLFLOW_TRACKING_URI"):
        return os.environ["MLFLOW_TRACKING_URI"]
    env = clip.ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "MLFLOW_TRACKING_URI" and value.strip():
                return value.strip().strip('"')
    return None


def flat_metrics(bench: dict) -> dict[str, float]:
    tp = bench["tracked_players"]
    out = {
        "recall": tp["recall"], "precision": tp["precision"],
        "position_error_mean_m": tp["position_error_mean_m"],
        "position_error_median_m": tp["position_error_median_m"],
        "position_error_p90_m": tp["position_error_p90_m"],
        "team_accuracy": tp["team_accuracy"],
        "tracks_per_player": tp["tracks_per_ground_truth_player_mean"],
        "raw_recall": bench["detections_on_pitch"]["recall"],
        "raw_precision": bench["detections_on_pitch"]["precision"],
        "ball_frame_share": bench["ball"]["frames_with_ball"] / bench["ball"]["frames"],
        "event_recall_1s": bench["events"]["within_1s"]["all"]["recall"],
        "event_recall_5s": bench["events"]["within_5s"]["all"]["recall"],
        "event_precision_5s": bench["events"]["within_5s"]["all"]["precision"],
        "detect_seconds_per_frame": bench["timing"]["detect_seconds_per_frame_mean"],
    }
    return {k: float(v) for k, v in out.items() if v is not None}


def main() -> None:
    import truststore

    truststore.inject_into_ssl()  # the network inspects HTTPS; use the Windows certificate store
    try:
        import mlflow
    except ImportError:
        raise SystemExit("mlflow isn't installed in this environment (needs mlflow-skinny and azureml-mlflow)")
    uri = tracking_uri()
    if not uri:
        raise SystemExit("MLFLOW_TRACKING_URI isn't set (the workspace's MLflow tracking URI, from the Azure portal)")
    bench = json.loads(clip.BENCHMARK.read_text(encoding="utf-8"))
    mlflow.set_tracking_uri(uri)
    mlflow.set_experiment(EXPERIMENT)
    with mlflow.start_run(run_name=f"{clip.STEM}-rfdetr-small-pretrained") as run:
        mlflow.set_tags({"match": clip.MATCH, "source": "SoccerTrack v2 (CC BY 4.0)", "stage": "pre-trained"})
        mlflow.log_params({
            "model": "rf-detr-small", "weights": "COCO, as released", "fine_tuned": False,
            "tiles": "5x2 rows 90-790 overlap 96", "person_min_score": clip.PERSON_MIN_SCORE,
            "ball_min_score": clip.BALL_MIN_SCORE, "fps_processed": clip.FPS / clip.STRIDE,
            "clip": f"{bench['clip']['from']}-{bench['clip']['to']}", "calibration_degree":
                json.loads(clip.CALIBRATION.read_text(encoding="utf-8"))["degree"],
            "match_radius_m": bench["tracked_players"]["match_radius_m"],
        })
        mlflow.log_metrics(flat_metrics(bench))
        mlflow.log_artifact(str(clip.BENCHMARK))
        mlflow.log_artifact(str(clip.CALIBRATION))
        print(f"logged run {run.info.run_id} to experiment {EXPERIMENT}")


if __name__ == "__main__":
    main()
