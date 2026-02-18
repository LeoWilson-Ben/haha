-- 语音匹配房间表（一对一语音通话）
-- 执行：mysql -u root -p lingshu < sql/migrate_voice_room.sql

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS `voice_room` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `room_id` VARCHAR(64) NOT NULL COMMENT '业务房间号，与 RTC channel 一致',
    `user_id_1` BIGINT NOT NULL,
    `user_id_2` BIGINT NOT NULL,
    `rtc_channel` VARCHAR(64) NOT NULL COMMENT 'Agora channel name',
    `status` VARCHAR(20) NOT NULL DEFAULT 'ongoing' COMMENT 'matching/ongoing/ended',
    `started_at` DATETIME DEFAULT NULL,
    `ended_at` DATETIME DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_room_id` (`room_id`),
    KEY `idx_status` (`status`),
    KEY `idx_user_1` (`user_id_1`),
    KEY `idx_user_2` (`user_id_2`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='语音匹配房间';
