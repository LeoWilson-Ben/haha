-- 建表/改表：互动通知表 + post 自定义标签字段（已有则跳过或注释下一行）
USE lingshu;

-- 1. 互动通知表
CREATE TABLE IF NOT EXISTS `notification` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `user_id` BIGINT NOT NULL COMMENT '接收人（帖子作者）',
    `type` VARCHAR(20) NOT NULL COMMENT 'comment/like/favorite/share',
    `from_user_id` BIGINT NOT NULL COMMENT '触发人',
    `post_id` BIGINT NOT NULL,
    `comment_id` BIGINT DEFAULT NULL COMMENT '仅 comment 时有',
    `content_snippet` VARCHAR(255) DEFAULT NULL COMMENT '评论内容摘要',
    `read` TINYINT NOT NULL DEFAULT 0,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_user_created` (`user_id`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='互动通知';

-- 2. post 表增加自定义标签字段（若已存在会报错，可忽略或注释本行）
ALTER TABLE `post` ADD COLUMN `tags_json` VARCHAR(500) DEFAULT NULL COMMENT '自定义标签名 JSON 数组';
