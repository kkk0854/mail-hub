-- ============================================================
-- MAIL HUB v1.1.0 -> v1.2.0 数据库迁移
-- 适用：SQLite（PostgreSQL 需改类型）
-- 执行：sqlite3 backend/data/mailhub.db < backend/migrations/migrate_v110_to_v120.sql
-- ============================================================

-- 1. 临时邮箱 Provider 插件配置表
CREATE TABLE IF NOT EXISTS temp_mail_provider_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_name TEXT NOT NULL UNIQUE,
    enabled BOOLEAN DEFAULT 1,
    priority INTEGER DEFAULT 10,
    config_json TEXT DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. mailboxes 增加 +tag 别名 & 演示数据字段
ALTER TABLE mailboxes ADD COLUMN is_alias BOOLEAN DEFAULT 0;
ALTER TABLE mailboxes ADD COLUMN real_main_email VARCHAR(255);
ALTER TABLE mailboxes ADD COLUMN is_demo BOOLEAN DEFAULT 0;

-- 3. registration_tasks 增加演示数据字段
ALTER TABLE registration_tasks ADD COLUMN is_demo BOOLEAN DEFAULT 0;

-- 4. messages 增加演示数据字段
ALTER TABLE messages ADD COLUMN is_demo BOOLEAN DEFAULT 0;

-- 5. parse_attempts 增加演示数据字段
ALTER TABLE parse_attempts ADD COLUMN is_demo BOOLEAN DEFAULT 0;

-- 6. parse_results 增加演示数据字段
ALTER TABLE parse_results ADD COLUMN is_demo BOOLEAN DEFAULT 0;

-- 7. mailbox_credentials 增加演示数据字段
ALTER TABLE mailbox_credentials ADD COLUMN is_demo BOOLEAN DEFAULT 0;

-- 8. 复合索引（幂等）
CREATE INDEX IF NOT EXISTS ix_temp_mail_provider_settings_name ON temp_mail_provider_settings (provider_name);
CREATE INDEX IF NOT EXISTS ix_registration_tasks_project_key ON registration_tasks (project_key);
CREATE INDEX IF NOT EXISTS ix_registration_tasks_claim_result ON registration_tasks (claim_result);
CREATE INDEX IF NOT EXISTS ix_mailboxes_is_demo ON mailboxes (is_demo);
CREATE INDEX IF NOT EXISTS ix_messages_is_demo ON messages (is_demo);

-- 注意：如果已存在旧表且 ALTER 失败（重复列），忽略错误即可，重复执行不会破坏数据。
