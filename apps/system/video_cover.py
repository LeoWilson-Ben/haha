# -*- coding: utf-8 -*-
"""
视频封面：从视频文件截取第一帧为图片，用于 OSS 上传。
检测视频旋转：ffprobe 读取编码尺寸与 rotation 元数据。
依赖系统已安装 ffmpeg/ffprobe（如：apt install ffmpeg / brew install ffmpeg）。
"""
import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def probe_video_rotation(video_path):
    """
    用 ffprobe 检测视频的编码尺寸与旋转信息。

    :param video_path: 视频文件路径（str 或 Path）
    :return: dict，例如:
        {
            "width": 1920,
            "height": 1080,
            "rotation": 90,        # 0/90/180/270，无则 0
            "display_width": 1080,  # 旋转后的显示宽
            "display_height": 1920,
            "has_rotation": True,
        }
        失败或非视频返回 None
    """
    video_path = Path(video_path)
    if not video_path.is_file():
        logger.warning("视频文件不存在: %s", video_path)
        return None
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        logger.warning("未找到 ffprobe，请安装 ffmpeg")
        return None
    try:
        out = subprocess.run(
            [
                ffprobe,
                "-v", "quiet",
                "-print_format", "json",
                "-show_streams",
                "-select_streams", "v:0",
                str(video_path),
            ],
            capture_output=True,
            timeout=15,
            check=True,
            text=True,
        )
        data = json.loads(out.stdout)
        streams = data.get("streams") or []
        if not streams:
            return None
        s = streams[0]
        w = int(s.get("width") or 0)
        h = int(s.get("height") or 0)
        if w <= 0 or h <= 0:
            return None
        rotation = 0
        tags = s.get("tags")
        if isinstance(tags, dict) and (tags.get("rotate") or tags.get("rotation")) is not None:
            rot = tags.get("rotate") or tags.get("rotation")
            try:
                rotation = int(float(rot))
            except (TypeError, ValueError):
                pass
        side_data = s.get("side_data")
        if rotation == 0 and isinstance(side_data, list):
            for item in side_data:
                if isinstance(item, dict) and "rotation" in item:
                    try:
                        rotation = int(float(item["rotation"]))
                    except (TypeError, ValueError):
                        pass
                    break
        if rotation not in (0, 90, 180, 270):
            rotation = 0
        if rotation in (90, 270):
            display_width, display_height = h, w
        else:
            display_width, display_height = w, h
        return {
            "width": w,
            "height": h,
            "rotation": rotation,
            "display_width": display_width,
            "display_height": display_height,
            "has_rotation": rotation != 0,
        }
    except subprocess.CalledProcessError as e:
        logger.warning("ffprobe 执行失败: %s %s", e.stderr, video_path)
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.warning("ffprobe 解析失败: %s", e)
    except Exception as e:
        logger.warning("检测视频旋转异常: %s", e)
    return None


def extract_first_frame(video_path, output_path=None, time_sec=0.0):
    """
    从视频文件截取一帧为 JPEG 图片。

    :param video_path: 视频文件路径（str 或 Path）
    :param output_path: 输出图片路径，默认在临时目录生成
    :param time_sec: 截取时间点（秒），默认 0 即第一帧
    :return: 成功返回输出图片路径（Path），失败返回 None
    """
    video_path = Path(video_path)
    if not video_path.is_file():
        logger.warning("视频文件不存在: %s", video_path)
        return None
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        logger.warning("未找到 ffmpeg，请安装后重试")
        return None
    if output_path is None:
        fd, output_path = tempfile.mkstemp(suffix=".jpg", prefix="video_cover_")
        os.close(fd)
    output_path = Path(output_path)
    try:
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i", str(video_path),
                "-ss", str(time_sec),
                "-vframes", "1",
                "-f", "image2",
                "-q:v", "2",
                str(output_path),
            ],
            capture_output=True,
            timeout=30,
            check=True,
        )
        if output_path.is_file() and output_path.stat().st_size > 0:
            return output_path
    except subprocess.CalledProcessError as e:
        logger.warning("ffmpeg 截帧失败: %s %s", e.stderr and e.stderr.decode("utf-8", errors="replace"), video_path)
    except Exception as e:
        logger.warning("截取视频封面异常: %s", e)
    return None
