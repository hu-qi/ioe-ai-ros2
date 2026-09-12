-- ============================================================
-- analysis_schema.sql — 统计分析插件表 DDL
-- 工程基线: app_mgr_object-0.2.1
-- 关联文档: doc/71 统计分析插件开发方案
-- ============================================================

-- 统计结果缓存表：按维度缓存统计结果，避免重复计算
CREATE TABLE IF NOT EXISTS analysis_cache (
    cache_key          TEXT    PRIMARY KEY,   -- 维度组合键，如 "step_duration|cls=一班|date=2026-09"
    dimension          TEXT    NOT NULL,      -- 统计维度：step_duration / student_cumulative / class_summary
    filters_json       TEXT,                  -- 过滤条件 JSON（cls / device_id / date_range）
    result_json        TEXT,                  -- 统计结果 JSON
    computed_at        INTEGER NOT NULL,      -- 计算时刻（epoch ms）
    report_count       INTEGER                -- 参与统计的报告数
);

-- 诊断结果表：每条诊断结果独立存储，支持历史追溯
CREATE TABLE IF NOT EXISTS diagnosis_results (
    diagnosis_id       TEXT    PRIMARY KEY,   -- 平台生成：D{timestamp}
    diagnosis_type     TEXT    NOT NULL,      -- bottleneck / persistent_error / sequence_chaos / student_regression
    scope              TEXT    NOT NULL,      -- class / student / step
    target_id          TEXT,                  -- 学员工号 / 步骤序号 / 班级名
    metric_value       REAL,                  -- 判断依据数值（如实际平均用时、遗漏率）
    threshold_value    REAL,                  -- 阈值（如 SOP×1.5、30%、20%）
    advice_text        TEXT,                  -- 教官行动建议文本
    computed_at        INTEGER NOT NULL,      -- 计算时刻
    date_window_start  INTEGER,               -- 统计时间窗起点
    date_window_end    INTEGER                -- 统计时间窗终点
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_cache_dimension  ON analysis_cache(dimension);
CREATE INDEX IF NOT EXISTS idx_diagnosis_type   ON diagnosis_results(diagnosis_type);
CREATE INDEX IF NOT EXISTS idx_diagnosis_target ON diagnosis_results(target_id);
CREATE INDEX IF NOT EXISTS idx_diagnosis_computed ON diagnosis_results(computed_at);

-- ------------------------------------------------------------
-- teaching_actions — 教学调整事件表 (P5, doc/01 §6.4 / doc/02 §4.4)
-- 教官记录教学调整 → 平台对比调整前后班级指标 → 改进效果验证
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS teaching_actions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    action_date     INTEGER NOT NULL,          -- 调整日期 (epoch ms)
    description     TEXT    NOT NULL,          -- 调整内容描述
    target_substep  INTEGER,                   -- 目标子步骤序号 (可空=全轮)
    process_name    TEXT    DEFAULT '',        -- 针对工序 (空=通用)
    class_name      TEXT    NOT NULL,          -- 班级
    created_at      INTEGER NOT NULL           -- 记录时刻 (epoch ms)
);

CREATE INDEX IF NOT EXISTS idx_ta_class   ON teaching_actions(class_name);
CREATE INDEX IF NOT EXISTS idx_ta_process ON teaching_actions(process_name);
