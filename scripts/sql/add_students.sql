-- ============================================================
-- add_students.sql — 新增学员示例（students 表，doc/04 §四学员台账）
-- 用法: sqlite3 app_mgr_object/config/app.db < scripts/sql/add_students.sql
-- 说明:
--   * id 为工号(唯一)，status 可选 active/graduated/dropped/deleted；
--   * created_at/updated_at 为 epoch 毫秒，以下用 strftime 自动生成当前时间；
--   * extra 为扩展字段 JSON 字符串，可省略。
-- 幂等: 使用 INSERT OR REPLACE，重复执行会覆盖同工号记录。
-- ============================================================

INSERT OR REPLACE INTO students
    (id, name, cls, trade, enroll_date, status, remark, extra, created_at, updated_at)
VALUES
    ('S101', '张伟',   '拆解一班', '火炮维修', '2025-09-01', 'active', '示例学员：新增-拆解', NULL,
     (strftime('%s','now') * 1000), (strftime('%s','now') * 1000)),
    ('S102', '王强',   '拆解一班', '火炮维修', '2025-09-01', 'active', '示例学员：新增-拆解', NULL,
     (strftime('%s','now') * 1000), (strftime('%s','now') * 1000)),
    ('S103', '李娜',   '组装二班', '底盘维修', '2025-09-01', 'active', '示例学员：新增-组装', NULL,
     (strftime('%s','now') * 1000), (strftime('%s','now') * 1000));

-- 执行后核对:
-- SELECT id, name, cls, trade, status FROM students WHERE id IN ('S101','S102','S103');
