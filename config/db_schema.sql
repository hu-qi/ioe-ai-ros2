-- ═══════════════════════════════════════════════════════════
-- 任务管理模块 — 数据库建表脚本
-- 引擎: SQLite3
-- 使用: sqlite3 /data/task_manager.db < config/db_schema.sql
-- ═══════════════════════════════════════════════════════════

PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

-- ==========================================================
-- 1. 起始仓位配置表（Web 可编辑）
-- ==========================================================
CREATE TABLE IF NOT EXISTS source_bay_config (
    bay_id      TEXT PRIMARY KEY,              -- A1001 ~ D1006
    cargo_type  INT NOT NULL,                  -- 1-6
    enabled     INT DEFAULT 1,                 -- 0=禁用, 1=启用
    update_time TIMESTAMP DEFAULT (datetime('now','localtime'))
);

-- ==========================================================
-- 2. 终点仓位配置表（Web 可编辑）
-- ==========================================================
CREATE TABLE IF NOT EXISTS dest_bay_config (
    bay_id      TEXT PRIMARY KEY,              -- T2001 ~ T4006
    cargo_type  INT NOT NULL,                  -- 1-6
    floor_no    INT,                           -- 2/3/4
    enabled     INT DEFAULT 1,
    update_time TIMESTAMP DEFAULT (datetime('now','localtime'))
);

-- ==========================================================
-- 3. 叉车状态表（status_poller 维护）
-- ==========================================================
CREATE TABLE IF NOT EXISTS robot_status (
    robot_id        INT PRIMARY KEY,           -- 1001, 1002
    status          TEXT DEFAULT 'OFFLINE',     -- IDLE/BUSY/OFFLINE/ERROR
    current_task_id TEXT,
    battery         INT DEFAULT 0,
    position_code   TEXT,
    update_time     TIMESTAMP DEFAULT (datetime('now','localtime'))
);

-- ==========================================================
-- 4. 起始仓位实时状态（bay_status_fusion 维护）
-- ==========================================================
CREATE TABLE IF NOT EXISTS source_bay_status (
    bay_id          TEXT PRIMARY KEY,
    cargo_type      INT,
    ai_detected     INT DEFAULT 0,             -- 0=无货, 1=有货
    bind_status     INT DEFAULT 0,             -- 0=未绑定, 1=已绑定, 2=绑定中
    debounce_count  INT DEFAULT 0,
    in_task         INT DEFAULT 0,
    last_seen       TIMESTAMP,
    bind_time       TIMESTAMP
);

-- ==========================================================
-- 5. 终点仓位实时状态（status_poller / rcs_callback_receiver 维护）
-- ==========================================================
CREATE TABLE IF NOT EXISTS dest_bay_status (
    bay_id       TEXT PRIMARY KEY,
    cargo_type   INT,
    is_empty     INT DEFAULT 1,                 -- 1=空, 0=有货
    updated_by   TEXT,                           -- 'rcs_callback' | 'polling'
    update_time  TIMESTAMP DEFAULT (datetime('now','localtime'))
);

-- ==========================================================
-- 6. 工作时间窗口配置（Web 可编辑）
-- ==========================================================
CREATE TABLE IF NOT EXISTS work_schedule (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    day_of_week  TEXT,                           -- 'mon-fri', 'sat', 'sun'
    start_time   TEXT,                           -- '08:00'
    end_time     TEXT,                           -- '18:00'
    enabled      INT DEFAULT 1
);

-- ==========================================================
-- 7. 任务实例表（workflow_engine 维护）
-- ==========================================================
CREATE TABLE IF NOT EXISTS task_instances (
    task_id        TEXT PRIMARY KEY,
    workflow_name  TEXT,
    src_bay        TEXT,
    dst_bay        TEXT,
    robot_id       INT,
    cargo_type     INT,
    rcs_task_no    TEXT,                         -- RCS 返回的任务流水号
    status         TEXT DEFAULT 'PENDING',        -- PENDING/RUNNING/SUCCESS/FAILED/MANUAL
    current_state  TEXT,                         -- 工作流当前状态
    context_blob   BLOB,                         -- Pickle 序列化
    created_at     TIMESTAMP DEFAULT (datetime('now','localtime')),
    completed_at   TIMESTAMP
);

-- ==========================================================
-- 8. 系统通用配置表
-- ==========================================================
CREATE TABLE IF NOT EXISTS sys_config (
    config_key   TEXT PRIMARY KEY,
    config_value TEXT,
    update_time  TIMESTAMP DEFAULT (datetime('now','localtime'))
);

-- ==========================================================
-- 初始化默认配置
-- ==========================================================
INSERT OR IGNORE INTO sys_config (config_key, config_value) VALUES
    ('debounce_threshold', '3'),
    ('trigger_scan_interval_sec', '2'),
    ('robot_poll_interval_sec', '3'),
    ('dest_bay_poll_interval_sec', '60'),
    ('transport_timeout_sec', '600'),
    ('max_concurrent_tasks', '10');

-- ==========================================================
-- 初始化默认工作时间窗口
-- ==========================================================
INSERT OR IGNORE INTO work_schedule (day_of_week, start_time, end_time, enabled)
VALUES ('mon-fri', '08:00', '18:00', 1);