-- 群公告：im_group 增加 announcement 字段
-- 执行：mysql -u root -p lingshu < sql/migrate_group_announcement.sql

ALTER TABLE im_group ADD COLUMN announcement VARCHAR(500) NULL DEFAULT NULL COMMENT '群公告';
