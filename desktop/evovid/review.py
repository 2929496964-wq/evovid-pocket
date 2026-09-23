"""对用户上传的真实视频执行可追溯质检与受控曝光预览，不覆盖源文件。

OpenCV 指标只是诊断线索，不代表美感、人物身份或语义正确。
未知输入只有在用户明确允许后才改变曝光；一次处理，不无限重试。
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from pydantic import BaseModel, ConfigDict
from typing import Literal

from .render import ffmpeg_path
from .vision import analyze_video

MAX_BYTES = 32 * 1024 * 1024
MAX_STORAGE = 384 * 1024 * 1024
ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")


class ReviewAction(BaseModel):
    """API 只接受两种预定义操作；不接收命令、路径、滤镜表达式或任意 URL。"""
    model_config = ConfigDict(extra="forbid")
    action: Literal["preserve", "brighten"]
    confirmed: bool = False


def utc_now() -> str:
    """日志时间统一使用带时区 UTC，避免把本机时区当赛事截止时区。"""
    return datetime.now(timezone.utc).isoformat()


def digest_file(path: Path) -> str:
    """流式计算源文件 SHA256，不把二进制素材加载到提示词或日志。"""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def proposal_for(report: dict[str, Any]) -> dict[str, Any]:
    """把 OpenCV 暗帧信息转换为有界预览提案；全黑或纹理不足时不修复。"""
    dark = [x for x in report["samples"] if x["mean_luma"] < 20 or x["dark_fraction"] > .95]
    informative = [x for x in dark if 2 <= x["mean_luma"] < 35 and x["sharpness"] >= .15]
    if not dark:
        return {"action": "preserve", "can_brighten": False, "reason": "No low-exposure samples were flagged.", "intervals": []}
    if len(informative) != len(dark):
        return {"action": "human_review", "can_brighten": False,
                "reason": "Some dark samples contain too little visible information. Brightening cannot reconstruct missing detail.", "intervals": []}
    samples = report["samples"]
    duration = float(report["duration_seconds"])
    intervals: list[list[float]] = []
    for i, item in enumerate(samples):
        if item not in informative:
            continue
        left = 0.0 if i == 0 else (samples[i-1]["time"] + item["time"]) / 2
        right = duration if i == len(samples)-1 else (samples[i+1]["time"] + item["time"]) / 2
        if intervals and left <= intervals[-1][1] + .01:
            intervals[-1][1] = right
        else:
            intervals.append([left, right])
    return {"action": "offer_exposure_preview", "can_brighten": True, "gamma": 1.6,
            "reason": "Low exposure with measurable texture. An intentional night shot may be correct; user approval is required.",
            "intervals": [[round(a, 3), round(b, 3)] for a, b in intervals],
            "limitations": ["Intervals are inferred from sparse samples.", "Preview changes exposure, not semantic content."]}


class ReviewStore:
    """单实例本地目录存储。只接收服务端生成的 ID，保留输入和审计记录。"""
    def __init__(self, home: Path):
        self.home = Path(home) / "reviews"
        self.home.mkdir(parents=True, exist_ok=True)
        self.gate = threading.BoundedSemaphore(1)
        # 上次中断的写入不能伪装成完成，可重新分析而不复用半成品。
        for path in self.home.glob("*/report.json"):
            try:
                report = json.loads(path.read_text(encoding="utf-8"))
                if report.get("status") == "processing":
                    report["status"] = "interrupted"
                    self.save(path.parent.name, report)
            except (ValueError, OSError):
                continue

    @contextmanager
    def exclusive(self) -> Iterator[None]:
        """限制同时上传/解码/处理的数量，防止多个请求占满内存。"""
        if not self.gate.acquire(blocking=False):
            raise RuntimeError("A video review is already running. Please wait.")
        try:
            yield
        finally:
            self.gate.release()

    def folder(self, review_id: str) -> Path:
        """验证 ID 和目录位置；不允许软链接把视频读取引向工作区外。"""
        if not ID_PATTERN.fullmatch(review_id):
            raise ValueError("Invalid review id.")
        path = self.home / review_id
        if path.is_symlink() or path.resolve().parent != self.home.resolve():
            raise ValueError("Unsafe review path.")
        return path

    def check_capacity(self) -> None:
        """小型本地库的容量门，预留一个输入和一个输出的空间。"""
        used = sum(x.stat().st_size for x in self.home.rglob("*") if x.is_file() and not x.is_symlink())
        free = shutil.disk_usage(self.home).free
        if used > MAX_STORAGE - MAX_BYTES * 2 or free < MAX_BYTES * 3:
            raise RuntimeError("Review storage is full. Delete an old review before uploading.")

    def save(self, review_id: str, report: dict[str, Any]) -> None:
        """通过临时文件原子替换 JSON，避免中途崩溃留下半份报告。"""
        folder = self.folder(review_id)
        folder.mkdir(parents=True, exist_ok=True)
        temp = folder / "report.json.tmp"
        temp.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        temp.replace(folder / "report.json")

    def get(self, review_id: str) -> dict[str, Any]:
        """读取一份已有报告；没有报告的半成品不展示给用户。"""
        path = self.folder(review_id) / "report.json"
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError("Review not found.")
        return json.loads(path.read_text(encoding="utf-8"))

    def list(self) -> list[dict[str, Any]]:
        """只列出摘要，不泄露本机绝对路径或其他任务内容。"""
        items = []
        for path in self.home.glob("*/report.json"):
            try:
                r = self.get(path.parent.name)
                items.append({k: r[k] for k in ("id", "created_at", "status", "name", "source_kind")})
            except (ValueError, KeyError, OSError):
                continue
        return sorted(items, key=lambda x: x["created_at"], reverse=True)[:100]

    def analyze(self, review_id: str, *, demo: bool = False) -> dict[str, Any]:
        """执行真正解码和 CV 取样；用户文件与合成演示素材明确区分。"""
        source = self.folder(review_id) / "source.mp4"
        if source.is_symlink() or not source.is_file() or not 16 <= source.stat().st_size <= MAX_BYTES:
            raise ValueError("A bounded MP4 file is required.")
        with source.open("rb") as stream:
            header = stream.read(32)
        if header[4:8] != b"ftyp":
            raise ValueError("Only MP4/MOV media containers are supported, not playlists or URLs.")
        metrics = analyze_video(source, sample_count=60)
        report = {"schema_version": 2, "id": review_id, "created_at": utc_now(), "status": "analyzed",
                  "name": "Synthetic low-light test clip" if demo else "Local uploaded video",
                  "source_kind": "synthetic_fixture" if demo else "user_upload",
                  "input_sha256": digest_file(source), "input_bytes": source.stat().st_size,
                  "before": metrics, "after": None, "proposal": proposal_for(metrics), "selected_file": "source.mp4",
                  "adjustment_count": 0, "original_retained": True, "llm_used": False,
                  "decision_engine": "bounded_rule_policy", "source_is_neural_generated": "not_asserted",
                  "events": [{"at": utc_now(), "kind": "perception", "detail": "Decoded source with OpenCV; no cloud upload."},
                             {"at": utc_now(), "kind": "decision", "detail": "Generate a preview proposal, never change a file without approval."}]}
        self.save(review_id, report)
        return report

    def apply(self, review_id: str, request: ReviewAction) -> dict[str, Any]:
        """最多一次受控曝光预览；已处理版本仍需用户看画面，不自动判定美感。"""
        if not request.confirmed:
            raise ValueError("Explicit approval is required.")
        folder = self.folder(review_id)
        report = self.get(review_id)
        if report["status"] == "processing":
            raise ValueError("Review is currently being processed.")
        source = folder / "source.mp4"
        if source.is_symlink() or digest_file(source) != report["input_sha256"]:
            raise ValueError("Source content changed. Upload and analyze it again.")
        if request.action == "preserve":
            report["selected_file"] = "source.mp4"
            report["status"] = "preserved"
            report["events"].append({"at": utc_now(), "kind": "human_decision", "detail": "Keep original; intentional darkness may be correct."})
            self.save(review_id, report)
            return report
        if report["adjustment_count"] >= 1:
            raise ValueError("The one-preview limit has been reached. Original is retained.")
        if not report["proposal"]["can_brighten"]:
            raise ValueError("This clip has no safe exposure-preview proposal.")
        report["status"] = "processing"
        report["events"].append({"at": utc_now(), "kind": "human_approval", "detail": "User approved one local gamma preview; source stays unchanged."})
        self.save(review_id, report)
        temp = folder / "preview.part.mp4"
        output = folder / "preview.mp4"
        start = time.perf_counter()
        try:
            intervals = report["proposal"]["intervals"]
            expression = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in intervals)
            # 滤镜参数只来自固定策略与已验证浮点数，不拼接用户命令。
            args = [ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                    "-protocol_whitelist", "file,pipe", "-i", str(source), "-map", "0:v:0", "-map", "0:a:0?",
                    "-vf", f"eq=gamma=1.6:enable='{expression}'", "-c:v", "libx264", "-crf", "20",
                    "-threads", "2", "-filter_threads", "1", "-pix_fmt", "yuv420p", "-c:a", "copy",
                    "-map_metadata", "-1", "-movflags", "+faststart", "-fs", str(MAX_BYTES), str(temp)]
            proc = subprocess.run(args, capture_output=True, timeout=150, check=False)
            if proc.returncode or not temp.exists():
                raise RuntimeError("Local video encoding failed; original retained.")
            after = analyze_video(temp, sample_count=60)
            before = report["before"]
            if abs(after["duration_seconds"] - before["duration_seconds"]) > max(.1, 1/before["fps"]):
                raise RuntimeError("Preview duration changed; output rejected.")
            if (after["width"], after["height"]) != (before["width"], before["height"]):
                raise RuntimeError("Preview geometry changed; output rejected.")
            if digest_file(source) != report["input_sha256"]:
                raise RuntimeError("Source integrity check failed.")
            temp.replace(output)
            report.update(status="adjusted_for_review", after=after, selected_file="preview.mp4", adjustment_count=1,
                          preview_sha256=digest_file(output), process_seconds=round(time.perf_counter()-start, 4),
                          audio_policy="First audio stream copied when present; no synthetic audio added.")
            report["events"].extend([
                {"at": utc_now(), "kind": "tool_call", "detail": "FFmpeg gamma=1.6 only in CV-proposed intervals; maximum one preview."},
                {"at": utc_now(), "kind": "verification", "detail": "Re-analyzed output, checked duration/geometry and original SHA256."},
                {"at": utc_now(), "kind": "human_review_required", "detail": "Fewer low-light flags do not prove better aesthetic quality."}])
            self.save(review_id, report)
            return report
        except Exception as exc:
            temp.unlink(missing_ok=True)
            report["status"] = "failed"
            report["selected_file"] = "source.mp4"
            report["events"].append({"at": utc_now(), "kind": "failed", "detail": type(exc).__name__ + "; original retained."})
            self.save(review_id, report)
            raise

    def delete(self, review_id: str) -> None:
        """仅删除明确选中的单份 review；不扫描用户磁盘或其他项目。"""
        self.get(review_id)
        shutil.rmtree(self.folder(review_id))
