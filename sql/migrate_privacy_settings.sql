-- 个人信息隐私设置：控制他人可见的展示项
-- 默认：简介1 定位1 年龄1 出生日期0
SET NAMES utf8mb4;

-- 执行前若列已存在会报错，可单独注释已执行的语句
ALTER TABLE `user_profile` ADD COLUMN `show_intro` TINYINT NOT NULL DEFAULT 1 COMMENT '展示简介 0否1是';
ALTER TABLE `user_profile` ADD COLUMN `show_location` TINYINT NOT NULL DEFAULT 1 COMMENT '展示定位 0否1是';
ALTER TABLE `user_profile` ADD COLUMN `show_age` TINYINT NOT NULL DEFAULT 1 COMMENT '展示年龄 0否1是';
ALTER TABLE `user_profile` ADD COLUMN `show_birth_date` TINYINT NOT NULL DEFAULT 0 COMMENT '展示出生日期 0否1是';
