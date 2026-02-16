-- 用户资料：出生日期增加时分
-- 执行：mysql -u root -p lingshu < migrate_birth_time.sql

ALTER TABLE user_profile ADD COLUMN birth_time VARCHAR(10) DEFAULT NULL COMMENT '出生时辰 HH:mm' AFTER birth_date;
