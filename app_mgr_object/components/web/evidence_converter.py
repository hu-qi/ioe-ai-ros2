#!/usr/bin/env python3
"""
evidence_converter.py — 证据图 BMP→JPG 转换 + 缩略图（P3，doc/01 §七）

职责:
  - 将 evidence 表中待转换记录（BMP 落盘、jpg_path 为空）批量转换:
    BMP → JPG（展示用）+ 缩略图（列表页用）；
  - 端侧绝对路径（跨机不可达，file_path 不存在）跳过不报错——
    此类记录来自整包兜底通道的 round.evidence[].file 关联登记；
  - 转换结果回写 evidence.jpg_path / thumb_path。

用法:
  conv = EvidenceConverter(repo, logger)
  conv.convert_pending(limit=50)   # 返回 (成功数, 跳过数, 失败数)

线程安全: 每次调用独立执行，无共享状态；由插件线程池周期调度。
"""

import os
import io
from typing import Optional, Tuple

from PIL import Image

from .report_repo import ReportRepo

THUMB_MAX_EDGE = 240          # 缩略图最长边（px）
JPG_QUALITY = 85


class EvidenceConverter:
    """证据图格式转换器（Pillow 同步实现，调用方决定执行线程）"""

    def __init__(self, repo: ReportRepo, logger=None,
                 thumb_max_edge: int = THUMB_MAX_EDGE, jpg_quality: int = JPG_QUALITY):
        self._repo = repo
        self._logger = logger
        self._thumb_max_edge = thumb_max_edge
        self._jpg_quality = jpg_quality

    # ------------------------------------------------------------------
    def convert_pending(self, limit: int = 50) -> Tuple[int, int, int]:
        """批量转换待处理记录。Returns: (converted, skipped, failed)"""
        pending = self._repo.list_pending_conversion(limit)
        converted = skipped = failed = 0
        for row in pending:
            try:
                ok, is_skip = self._convert_one(row)
                if ok:
                    converted += 1
                elif is_skip:
                    skipped += 1
                else:
                    failed += 1
            except Exception as e:
                failed += 1
                if self._logger:
                    self._logger.error(f"证据转换异常 id={row.get('id')}: {e}")
        if self._logger and (converted or skipped or failed):
            self._logger.info(
                f"证据转换批次完成: converted={converted} skipped={skipped} failed={failed}"
            )
        return converted, skipped, failed

    # ------------------------------------------------------------------
    def _convert_one(self, row: dict) -> Tuple[bool, bool]:
        """转换单条。Returns: (success, is_skip)"""
        bmp_path = row.get("file_path") or ""
        if not bmp_path or not os.path.exists(bmp_path):
            # 端侧绝对路径登记记录（平台无该文件）→ 标记为已处理（jpg 留空）避免反复重扫
            self._repo.update_evidence_converted(row["id"], jpg_path="", thumb_path="")
            return False, True

        try:
            with Image.open(bmp_path) as img:
                img = img.convert("RGB")

                base, _ext = os.path.splitext(bmp_path)
                jpg_path = base + ".jpg"
                thumb_path = base + "_thumb.jpg"

                img.save(jpg_path, "JPEG", quality=self._jpg_quality)

                thumb = img.copy()
                thumb.thumbnail((self._thumb_max_edge, self._thumb_max_edge))
                thumb.save(thumb_path, "JPEG", quality=self._jpg_quality)
        except Exception as e:
            if self._logger:
                self._logger.error(f"BMP 解码失败 {bmp_path}: {e}")
            return False, False

        self._repo.update_evidence_converted(row["id"], jpg_path, thumb_path)
        return True, False
