-- 用户中医体质：供今日养生推荐使用
-- 体质类型：气虚、阳虚、阴虚、痰湿、湿热、血瘀、气郁、特禀、平和 等
SET NAMES utf8mb4;

ALTER TABLE `user_profile` ADD COLUMN `constitution` VARCHAR(32) DEFAULT NULL COMMENT '中医体质' AFTER `xiyongshen`;
