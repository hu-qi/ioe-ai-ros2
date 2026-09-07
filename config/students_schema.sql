-- ============================================================
-- students_schema.sql — 学员档案表 DDL
-- 工程基线: app_mgr_object-0.2.1
-- 关联文档: doc/69 学员管理插件开发方案
-- 对齐: doc/38 §3 student 对象, doc/45 §2 student 字段
-- ============================================================

-- 学员档案表：工号 id 作为主键，与边缘端 student.id 直接对齐
CREATE TABLE IF NOT EXISTS students (
    id            TEXT    PRIMARY KEY,             -- 工号，唯一标识，如 S2024001
    name          TEXT    NOT NULL,                -- 姓名
    cls           TEXT,                             -- 班级（对应边缘端 student.cls）
    trade         TEXT,                             -- 工种，如"火炮维修"、"底盘维修"
    enroll_date   TEXT,                             -- 入学日期，ISO 格式 YYYY-MM-DD
    status        TEXT    NOT NULL DEFAULT 'active'
                          CHECK (status IN ('active','graduated','dropped','deleted')),
    remark        TEXT,                             -- 备注
    extra         TEXT,                             -- 扩展字段，JSON 字符串
    created_at    INTEGER NOT NULL,                 -- 创建时间（epoch ms）
    updated_at    INTEGER NOT NULL                  -- 更新时间（epoch ms）
);

-- 检索索引：name / cls / status 高频查询
CREATE INDEX IF NOT EXISTS idx_students_name   ON students(name);
CREATE INDEX IF NOT EXISTS idx_students_cls    ON students(cls);
CREATE INDEX IF NOT EXISTS idx_students_status ON students(status);
