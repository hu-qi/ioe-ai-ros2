#!/usr/bin/env python3
"""
diagnosis_rules_loader.py — 诊断规则 YAML 加载器（P2，doc/02 §5.1 / doc/03 §2.2）

加载 config/diagnosis_rules.yaml，产出规则对象映射:
  {
    "processes": {"拆解": {rule_type: Rule}, ...},
    "common":    {rule_type: Rule, ...},
  }

回退链（doc/02 §4.2）: 工序专属规则 → common 通用规则 → 无规则跳过。
文件缺失/损坏时返回仅含内置默认 common 规则的可用结构（降级不抛异常）。
"""

import os
from dataclasses import dataclass, field
from typing import Dict, Optional

import yaml

DEFAULT_RULES_PATH = os.path.abspath(
    os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "..", "config", "diagnosis_rules.yaml")
)

# 支持的规则类型（五维 + 退步预警）
RULE_TYPES = ("bottleneck", "error", "sequence", "interval", "stddev", "regression")


@dataclass
class DiagnosisRule:
    """单条诊断规则（来自 YAML，引擎按 type 分派计算）"""
    type: str
    threshold: float
    enabled: bool = True
    suggestion: str = ""
    substep_index: Optional[int] = None      # None=对所有步骤生效
    window_recent: int = 3                    # regression 专用
    window_history: int = 5                   # regression 专用
    source: str = ""                          # 工序名或 "common"（调试用）


def _builtin_common_rules() -> Dict[str, DiagnosisRule]:
    """内置默认通用规则（对齐原 DEFAULT_THRESHOLDS 默认值，文件缺失时降级用）。"""
    return {
        "bottleneck": DiagnosisRule("bottleneck", 1.5, True, "该步骤需在下次课重点讲解", source="builtin"),
        "error": DiagnosisRule("error", 0.30, True, "需增加该步骤的专项训练", source="builtin"),
        "sequence": DiagnosisRule("sequence", 0.20, True, "需强调步骤间的依赖关系", source="builtin"),
        "interval": DiagnosisRule("interval", 5000, True, "该步骤与下一步衔接卡壳，需明确操作逻辑", source="builtin"),
        "stddev": DiagnosisRule("stddev", 0.5, True, "该步骤学员用时差异大，建议分享经验统一手法", source="builtin"),
        "regression": DiagnosisRule("regression", 0.85, True, "建议安排个别辅导",
                                    window_recent=3, window_history=5, source="builtin"),
    }


def _parse_rule(item: dict, source: str) -> Optional[DiagnosisRule]:
    rtype = (item.get("type") or "").strip()
    if rtype not in RULE_TYPES:
        return None
    try:
        threshold = float(item.get("threshold", 0))
    except (TypeError, ValueError):
        return None
    idx = item.get("substep_index")
    try:
        idx = int(idx) if idx is not None else None
    except (TypeError, ValueError):
        idx = None
    try:
        wr = int(item.get("window_recent", 3))
        wh = int(item.get("window_history", 5))
    except (TypeError, ValueError):
        wr, wh = 3, 5
    return DiagnosisRule(
        type=rtype,
        threshold=threshold,
        enabled=bool(item.get("enabled", True)),
        suggestion=str(item.get("suggestion", "")),
        substep_index=idx,
        window_recent=wr,
        window_history=wh,
        source=source,
    )


def _parse_group(items: list, source: str) -> Dict[str, DiagnosisRule]:
    """一组规则列表 → {rule_type: Rule}（同类型后条覆盖前条）。"""
    out: Dict[str, DiagnosisRule] = {}
    for item in items or []:
        if not isinstance(item, dict):
            continue
        rule = _parse_rule(item, source)
        if rule is not None:
            out[rule.type] = rule
    return out


def _candidate_paths() -> list:
    """候选路径: 仓库根 config/（运行时 CWD）→ 包相对 config/（app_mgr_object/config/）。"""
    pkg_rel = os.path.join(
        os.path.dirname(os.path.realpath(__file__)), "..", "..", "..", "config", "diagnosis_rules.yaml"
    )
    return [os.path.abspath(os.path.join("config", "diagnosis_rules.yaml")), os.path.abspath(pkg_rel)]


def load_diagnosis_rules(path: str = None) -> dict:
    """加载诊断规则。返回 {"processes": {name: {type: Rule}}, "common": {type: Rule}}。

    候选路径: 显式 path → 仓库根 config/ → 包相对 config/；
    全部缺失/损坏时降级为内置默认 common 规则。
    """
    data = None
    candidates = [path] if path else _candidate_paths()
    for candidate in candidates:
        try:
            with open(candidate, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            break
        except (IOError, yaml.YAMLError):
            continue

    if not data:
        return {"processes": {}, "common": _builtin_common_rules()}

    processes = {}
    for p in data.get("processes") or []:
        if not isinstance(p, dict) or not p.get("name"):
            continue
        group = _parse_group(p.get("rules"), str(p["name"]))
        if group:
            processes[str(p["name"])] = group

    common = _parse_group(data.get("common_rules"), "common") or _builtin_common_rules()
    return {"processes": processes, "common": common}


# ---------------------------------------------------------------------------
# 规则写回（系统设置页 G1，doc/02 §6.1 /settings）
# ---------------------------------------------------------------------------
def _rule_to_dict(rule: DiagnosisRule) -> dict:
    """规则对象 → YAML 节点 dict（与 _parse_rule 字段一一对应）。"""
    d = {
        "type": rule.type,
        "threshold": rule.threshold,
        "enabled": rule.enabled,
        "suggestion": rule.suggestion,
    }
    if rule.substep_index is not None:
        d["substep_index"] = rule.substep_index
    if rule.type == "regression":
        d["window_recent"] = rule.window_recent
        d["window_history"] = rule.window_history
    return d


def _resolved_rules_path(path: str = None) -> str:
    """写回目标路径: 显式 path → 已存在的候选 → 第一个候选（仓库根 config/）。"""
    if path:
        return os.path.abspath(path)
    candidates = _candidate_paths()
    for c in candidates:
        if os.path.exists(c):
            return c
    return candidates[0]


def load_rules_raw(path: str = None) -> dict:
    """读取规则 YAML 原始结构（供 GET 展示与 PUT 合并），文件缺失返回空骨架。"""
    target = _resolved_rules_path(path)
    try:
        with open(target, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except (IOError, yaml.YAMLError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    return data


def save_rules_raw(data: dict, path: str = None) -> str:
    """规则结构写回 YAML（先写临时文件再原子替换），返回实际写入路径。"""
    target = _resolved_rules_path(path)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    os.replace(tmp, target)
    return target
