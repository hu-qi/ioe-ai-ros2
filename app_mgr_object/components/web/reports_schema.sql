-- ============================================================
-- reports_schema.sql — 报告接收插件数据库 schema
-- 工程基线: app_mgr_object-0.2.1
-- 关联文档: doc/38 (整包 schema 1.0), doc/45 (增量 schema 1.1 + doc/58 统一计时)
-- 六张表: reports / report_steps / report_substeps / report_events / report_progress / subscriptions
-- ============================================================

-- ------------------------------------------------------------
-- 1. reports — 报告主表：一轮操作的元信息
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reports (
    report_id           TEXT    PRIMARY KEY,            -- 平台生成: R{device_id}_{round_start_ms}
    device_id           TEXT    NOT NULL,               -- 工位设备标识
    student_id          TEXT,                           -- 关联 students.id; 未绑定=NULL
    student_name        TEXT,                           -- 冗余存边缘端上报时的 name
    student_cls         TEXT,                           -- 冗余存 cls
    student_bound       INTEGER NOT NULL DEFAULT 0,    -- 0=未关联/未绑定 / 1=已关联 students 表
    process_name        TEXT,
    process_type        TEXT,                           -- disass / assembly (doc/38 §6)
    finish_reason       TEXT,                           -- completed / manual / timeout / reset
    is_stub             INTEGER NOT NULL DEFAULT 0,    -- 0=完整 / 1=存根(增量先到,待整包补全)
    start_ms            INTEGER NOT NULL,               -- 轮次起点 (引擎单调绝对 ms, doc/45 §5)
    end_ms              INTEGER,                        -- 轮次终点 (引擎单调绝对 ms)
    duration_ms         REAL,                           -- 用时 (= end_ms - start_ms, 可能小数 ms)
    process_elapsed_ms  INTEGER,                        -- 操作用时 (引擎单调差值, doc/58)
    total_score         REAL,                           -- 综合得分 (doc/38 §7 后续扩展字段)
    grade_level         TEXT,                           -- 评分等级: 优秀/良好/合格/不合格 (doc/01 §八, P1 评分引擎)
    raw_json_path       TEXT,                           -- 原始 JSON 文件留存路径
    ts_upload_ms        INTEGER NOT NULL,               -- 上报时刻 (epoch ms, 唯一墙钟时间)
    created_at          INTEGER NOT NULL                -- 平台入库时刻 (epoch ms)
);

-- ------------------------------------------------------------
-- 2. report_steps — 步骤聚合表：8 步骤级元信息
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS report_steps (
    report_id       TEXT    NOT NULL,
    idx             INTEGER NOT NULL,                   -- 步骤序号 1..8
    name            TEXT,
    state           INTEGER,                            -- 0 未开始 / 1 进行中 / 2 完成 / 3 跳过
    start_ms        INTEGER,                            -- 步骤起始 (引擎单调绝对 ms, doc/58 v1.1)
    end_ms          INTEGER,                            -- 步骤结束 (引擎单调绝对 ms, doc/58 v1.1)
    duration_ms     REAL,                               -- 步骤用时 ms
    interval_ms     REAL,                               -- 与上一步间隔 (= 本步 start - 上步 end, doc/58 v1.1)
    PRIMARY KEY (report_id, idx),
    FOREIGN KEY (report_id) REFERENCES reports(report_id)
);

-- ------------------------------------------------------------
-- 3. report_substeps — 子步骤明细表：全局连续子步骤
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS report_substeps (
    report_id           TEXT    NOT NULL,
    idx                 INTEGER NOT NULL,               -- 子步骤全局序号 1..N
    name                TEXT,
    state               INTEGER,                        -- 0..3
    start_ms            INTEGER,                        -- 子步骤起始 (引擎单调绝对 ms, doc/58 v1.1)
    end_ms              INTEGER,                        -- 子步骤结束 (引擎单调绝对 ms, doc/58 v1.1)
    duration_ms         REAL,                           -- 最近一次片段用时 ms
    count               INTEGER,                        -- 操作片段数 (>1=重复/中断重入)
    total_duration_ms   REAL,                           -- 全部片段累计用时 ms
    timeout             INTEGER,                        -- 0/1 bool
    std_duration_ms     REAL,                           -- SOP 标准用时 ms (doc/01 §八, P1 评分引擎)
    over_std            INTEGER DEFAULT 0,              -- 超标 0/1 (实际>标准)
    omitted             INTEGER DEFAULT 0,              -- 遗漏 0/1
    score               REAL,                           -- 子步骤得分 (P1 评分引擎回写)
    sequence_error      INTEGER DEFAULT 0,              -- 顺序错误 0/1 (P1 评分引擎回写)
    segments            TEXT,                           -- 操作片段明细 (JSON 数组, 可选)
    PRIMARY KEY (report_id, idx),
    FOREIGN KEY (report_id) REFERENCES reports(report_id)
);

-- ------------------------------------------------------------
-- 4. report_events — 事件流表：原子级时序事件
--    天然去重键: (report_id, ts, kind, sub)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS report_events (
    report_id       TEXT    NOT NULL,
    ts              INTEGER NOT NULL,                   -- 相对轮次起点偏移 ms (= 引擎绝对 ts - round_start_ms)
    kind            INTEGER NOT NULL,                   -- 0 START / 1 COMPLETE / 2 INTERRUPT / 3 TIMEOUT / 4 FINISH_EOF / 5 FINISH_EIO
    step            INTEGER,
    sub             INTEGER,
    source          TEXT    DEFAULT 'batch',            -- batch=整包 / delta=增量
    PRIMARY KEY (report_id, ts, kind, sub),
    FOREIGN KEY (report_id) REFERENCES reports(report_id)
);

-- ------------------------------------------------------------
-- 5. report_progress — 实时进度快照表：增量上报携带的进度状态
--    供 P3 看板插件实时展示学员操作进度
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS report_progress (
    report_id           TEXT    PRIMARY KEY,
    device_id           TEXT    NOT NULL,
    round_start_ms      INTEGER NOT NULL,
    done                INTEGER,                        -- 已完成子步骤数
    total               INTEGER,                        -- 总子步骤数
    current             TEXT,                           -- 当前进行中子步骤名 (空串=无进行中)
    current_sub_index   INTEGER,                        -- 当前进行中子步骤全局序号 (0=无进行中, doc/45 v1.1)
    process_elapsed_ms  INTEGER,                        -- 本批上报时刻操作用时 (引擎单调差值, doc/58)
    last_delta_ts       INTEGER,                        -- 最近一次增量事件 ts (相对偏移)
    updated_at          INTEGER NOT NULL,               -- 最近增量上报时刻 (epoch ms)
    FOREIGN KEY (report_id) REFERENCES reports(report_id)
);

-- ------------------------------------------------------------
-- 6. subscriptions — 订阅状态表：设备级订阅管理
--    doc/45 §4: 支持多设备同时订阅 (逐台调用, 每 device_id 独立)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS subscriptions (
    device_id           TEXT    PRIMARY KEY,
    active              INTEGER NOT NULL DEFAULT 0,    -- 0/1
    note                TEXT,
    edge_ips            TEXT,                           -- 边缘端 IP 列表 (JSON 数组, 如 ["1.2.3.4","1.2.3.5"]); 平台全推
    edge_port           INTEGER,                        -- 边缘端监听端口（默认 9184）
    notify_status       TEXT,                           -- 推送通知状态: pending / sent / partial / failed
    notify_ts           INTEGER,                        -- 最近一次推送通知时刻 (epoch ms)
    notify_detail       TEXT,                           -- 各 IP 推送结果明细 (JSON 数组)
    subscribed_at_ms    INTEGER,                        -- 首次订阅时刻
    updated_at_ms       INTEGER,                        -- 最近状态变更时刻
    resubscribed        INTEGER NOT NULL DEFAULT 0     -- 0/1 重复订阅标记 (doc/45 §4.1)
);

-- ============================================================
-- 索引
-- ============================================================
-- ------------------------------------------------------------
-- 7. evidence — 证据图元数据表 (P3, doc/01 §七)
--    幂等键: (device_id, round_start_ms, sub, ts) — dev01 §2.3
--    两通道(实时/整包兜底)均按此键去重; BMP 原图落盘后异步转 JPG
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS evidence (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id           TEXT    NOT NULL,
    round_start_ms      INTEGER NOT NULL,
    sub                 INTEGER NOT NULL,
    ts                  INTEGER NOT NULL,
    file_path           TEXT    NOT NULL,               -- BMP 原图绝对/相对路径
    jpg_path            TEXT,                           -- 异步转 JPG 后的路径 (P3)
    thumb_path          TEXT,                           -- 缩略图路径 (P3)
    file_size           INTEGER,                        -- BMP 原始字节数
    keep_forever        INTEGER NOT NULL DEFAULT 0,    -- 1=永久保留(跳过清理)
    created_at          INTEGER NOT NULL,               -- 入库时刻 (epoch ms)
    UNIQUE(device_id, round_start_ms, sub, ts)
);

CREATE INDEX IF NOT EXISTS idx_evidence_round ON evidence(device_id, round_start_ms);
CREATE INDEX IF NOT EXISTS idx_evidence_sub   ON evidence(device_id, round_start_ms, sub);

CREATE INDEX IF NOT EXISTS idx_reports_device      ON reports(device_id);
CREATE INDEX IF NOT EXISTS idx_reports_student     ON reports(student_id);
CREATE INDEX IF NOT EXISTS idx_reports_start       ON reports(start_ms);
CREATE INDEX IF NOT EXISTS idx_reports_upload      ON reports(ts_upload_ms);
CREATE INDEX IF NOT EXISTS idx_reports_bound       ON reports(student_bound);
CREATE INDEX IF NOT EXISTS idx_progress_device     ON report_progress(device_id);
CREATE INDEX IF NOT EXISTS idx_progress_round      ON report_progress(round_start_ms);
CREATE INDEX IF NOT EXISTS idx_events_device_ts    ON report_events(report_id, ts);
CREATE INDEX IF NOT EXISTS idx_subscriptions_active ON subscriptions(active);
