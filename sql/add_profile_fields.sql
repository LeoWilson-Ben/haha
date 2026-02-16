-- 为 user_profile 增加出生日期字段（简介 intro 已存在）
-- 执行：mysql -u root -p lingshu < server/sql/add_profile_fields.sql

USE lingshu;

ALTER TABLE `user_profile` ADD COLUMN `birth_date` DATE DEFAULT NULL COMMENT '出生日期' AFTER `intro`;
