#!/usr/bin/env python3
"""
scoring_rules_loader_raw.py — 评分规则 YAML 原始读写（系统设置页，doc/03 §2.2.2）

与 diagnosis_rules_loader 的 raw 读写同模式：
  - load_scoring_rules_raw(): 读原始结构（GET 展示 / PUT 合并）
  - save_scoring_rules_raw(): 原子写回（tmp + os.replace）
引擎侧解析仍由 scoring_engine.load_scoring_rules 负责（结构校验在引擎加载时兜底）。
"""

import os
from typing import Dict, Any

import yaml


def _candidate_paths() -> list:
    pkg_rel = os.path.join(
        os.path.dirname(os.path.realpath(__file__)), "..", "..", "..", "config", "scoring_rules.yaml"
    )
    return [os.path.abspath(os.path.join("config", "scoring_rules.yaml")), os.path.abspath(pkg_rel)]


def _resolved_path(path: str = None) -> str:
    if path:
        return os.path.abspath(path)
    candidates = _candidate_paths()
    for c in candidates:
        if os.path.exists(c):
            return c
    return candidates[0]


def load_scoring_rules_raw(path: str = None) -> Dict[str, Any]:
    """读取评分规则 YAML 原始结构，文件缺失/损坏返回空骨架。"""
    target = _resolved_path(path)
    try:
        with open(target, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except (IOError, yaml.YAMLError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    return data


def save_scoring_rules_raw(data: Dict[str, Any], path: str = None) -> str:
    """评分规则结构写回 YAML（临时文件 + 原子替换），返回实际写入路径。"""
    target = _resolved_path(path)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    os.replace(tmp, target)
    return target
