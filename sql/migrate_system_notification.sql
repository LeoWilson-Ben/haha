-- 系统通知表：公告、帖子下架等，在消息-通知中展示
-- 执行：mysql -u root -p lingshu < migrate_system_notification.sql

USE lingshu;

CREATE TABLE IF NOT EXISTS `system_notification` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `user_id` BIGINT NOT NULL COMMENT '接收人',
    `type` VARCHAR(32) NOT NULL COMMENT 'announcement/post_removed',
    `title` VARCHAR(255) NOT NULL,
    `content` TEXT DEFAULT NULL,
    `extra_json` VARCHAR(1024) DEFAULT NULL COMMENT '如 announcementId, postId, linkUrl',
    `read` TINYINT NOT NULL DEFAULT 0,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_user_created` (`user_id`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='系统通知（公告、帖子下架等）';
