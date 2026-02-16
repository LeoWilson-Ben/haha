-- 用户 8 位唯一标识 user_code（基于注册时间，搜索时精确唯一）
-- 执行：mysql -u root -p lingshu < migrate_user_code.sql

ALTER TABLE `user` ADD COLUMN `user_code` VARCHAR(8) DEFAULT NULL COMMENT '8位唯一标识';
UPDATE `user` SET user_code = LPAD(MOD(id - 1, 100000000) + 1, 8, '0') WHERE user_code IS NULL;
ALTER TABLE `user` ADD UNIQUE KEY `uk_user_code` (`user_code`);
-- user_code 可为空：新用户创建后由应用层立即写入
