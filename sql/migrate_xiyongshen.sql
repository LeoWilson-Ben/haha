-- 喜属性（喜用神）字段，用于喜属性匹配
-- 执行：mysql -u root -p lingshu < migrate_xiyongshen.sql

ALTER TABLE user_profile ADD COLUMN xiyongshen VARCHAR(64) DEFAULT NULL COMMENT '喜用神 JSON 如 {"喜神":"水","用神":"木"}' AFTER birth_time;
