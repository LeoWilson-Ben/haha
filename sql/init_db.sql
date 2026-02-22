-- =============================================================================
-- 玄遇 / 玄语 数据库初始化脚本（合并版）
-- 用法：mysql -u root -p < sql/init_db.sql
-- 或分两步：先创建库再导入（若需指定库名）
--   mysql -u root -p -e "source /path/to/server/sql/init_db.sql"
-- =============================================================================

-- 1. 创建库
CREATE DATABASE IF NOT EXISTS lingshu DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE lingshu;
SET NAMES utf8mb4;

-- =============================================================================
-- 2. 主表结构（用户、帖子、IM、钱包等，已含后续迁移字段）
-- =============================================================================

-- ------------------------------ 4.1 用户与账户 ------------------------------
CREATE TABLE IF NOT EXISTS `user` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `mobile` VARCHAR(20) NOT NULL COMMENT '手机号',
    `password_hash` VARCHAR(255) DEFAULT NULL COMMENT 'BCrypt 加密',
    `nickname` VARCHAR(64) DEFAULT NULL,
    `avatar_url` VARCHAR(512) DEFAULT NULL,
    `gender` TINYINT DEFAULT NULL COMMENT '0未知 1男 2女',
    `status` TINYINT NOT NULL DEFAULT 1 COMMENT '0禁用 1正常',
    `minor_mode` TINYINT NOT NULL DEFAULT 0 COMMENT '未成年人模式 0关 1开',
    `minor_mode_pwd` VARCHAR(255) DEFAULT NULL,
    `last_bazi_edit_at` DATETIME DEFAULT NULL COMMENT '上次修改八字时间，用于每季1次',
    `user_code` VARCHAR(8) DEFAULT NULL COMMENT '8位唯一标识',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_mobile` (`mobile`),
    UNIQUE KEY `uk_user_code` (`user_code`),
    KEY `idx_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户主表';

CREATE TABLE IF NOT EXISTS `user_profile` (
    `user_id` BIGINT NOT NULL,
    `intro` VARCHAR(500) DEFAULT NULL COMMENT '个人简介',
    `birth_date` DATE DEFAULT NULL COMMENT '出生日期',
    `birth_time` VARCHAR(10) DEFAULT NULL COMMENT '出生时辰 HH:mm',
    `xiyongshen` VARCHAR(64) DEFAULT NULL COMMENT '喜用神 JSON 如 {"喜神":"水","用神":"木"}',
    `region_code` VARCHAR(32) DEFAULT NULL COMMENT '地域',
    `open_bazi_level` TINYINT DEFAULT 0 COMMENT '八字公开程度',
    `is_master` TINYINT NOT NULL DEFAULT 0 COMMENT '0否 1是名师',
    `real_name` VARCHAR(64) DEFAULT NULL COMMENT '实名',
    `id_card_hash` VARCHAR(128) DEFAULT NULL COMMENT '身份证号哈希',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户扩展资料';

CREATE TABLE IF NOT EXISTS `user_wallet` (
    `user_id` BIGINT NOT NULL,
    `balance` DECIMAL(18,4) NOT NULL DEFAULT 0,
    `frozen_amount` DECIMAL(18,4) NOT NULL DEFAULT 0,
    `version` INT NOT NULL DEFAULT 0 COMMENT '乐观锁',
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='资金账户';

CREATE TABLE IF NOT EXISTS `wallet_log` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `user_id` BIGINT NOT NULL,
    `type` VARCHAR(20) NOT NULL COMMENT 'recharge/consume/withdraw',
    `amount` DECIMAL(18,4) NOT NULL,
    `order_no` VARCHAR(64) DEFAULT NULL,
    `remark` VARCHAR(255) DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_user_created` (`user_id`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='资金流水';

CREATE TABLE IF NOT EXISTS `login_device` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `user_id` BIGINT NOT NULL,
    `device_id` VARCHAR(128) NOT NULL,
    `device_info` VARCHAR(512) DEFAULT NULL,
    `last_login_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_user_id` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='登录设备';

-- ------------------------------ 4.2 八字与命理 ------------------------------
CREATE TABLE IF NOT EXISTS `user_bazi` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `user_id` BIGINT NOT NULL,
    `calendar_type` VARCHAR(10) NOT NULL COMMENT 'solar/lunar',
    `birth_datetime` DATETIME NOT NULL,
    `time_zone` VARCHAR(32) DEFAULT NULL,
    `pillar_json` TEXT DEFAULT NULL COMMENT '四柱',
    `shishen_json` TEXT DEFAULT NULL COMMENT '十神',
    `shensha_json` TEXT DEFAULT NULL COMMENT '神煞',
    `xiyongshen_json` TEXT DEFAULT NULL COMMENT '喜用神',
    `next_editable_at` DATETIME DEFAULT NULL COMMENT '下次可修改日期',
    `algorithm_version` VARCHAR(20) DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_user_id` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户主八字';

CREATE TABLE IF NOT EXISTS `bazi_report` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `user_id` BIGINT NOT NULL,
    `bazi_id` BIGINT NOT NULL,
    `report_type` VARCHAR(20) NOT NULL COMMENT 'standard/deep',
    `content_json` LONGTEXT DEFAULT NULL,
    `pdf_url` VARCHAR(512) DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_user_id` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='命理报告';

CREATE TABLE IF NOT EXISTS `fengshui_record` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `user_id` BIGINT NOT NULL,
    `floor_plan_url` VARCHAR(512) DEFAULT NULL,
    `result_json` TEXT DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_user_id` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='风水分析记录';

CREATE TABLE IF NOT EXISTS `hepan_record` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `user_id` BIGINT NOT NULL,
    `target_user_id` BIGINT DEFAULT NULL,
    `result_json` TEXT DEFAULT NULL,
    `score` INT DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_user_id` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='合盘记录';

-- ------------------------------ 4.3 订单与支付 ------------------------------
CREATE TABLE IF NOT EXISTS `order_main` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `order_no` VARCHAR(64) NOT NULL,
    `user_id` BIGINT NOT NULL,
    `type` VARCHAR(20) NOT NULL COMMENT 'recharge/consume/withdraw',
    `amount` DECIMAL(18,4) NOT NULL,
    `pay_channel` VARCHAR(20) DEFAULT NULL,
    `pay_trade_no` VARCHAR(128) DEFAULT NULL,
    `status` VARCHAR(20) NOT NULL DEFAULT 'pending',
    `subject` VARCHAR(255) DEFAULT NULL,
    `extra_json` TEXT DEFAULT NULL,
    `paid_at` DATETIME DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_order_no` (`order_no`),
    KEY `idx_user_type_created` (`user_id`, `type`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='统一订单';

CREATE TABLE IF NOT EXISTS `withdraw_apply` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `user_id` BIGINT NOT NULL,
    `amount` DECIMAL(18,4) NOT NULL,
    `bank_card_snapshot` VARCHAR(500) DEFAULT NULL,
    `status` VARCHAR(20) NOT NULL DEFAULT 'pending' COMMENT 'pending/approved/rejected',
    `audit_by` BIGINT DEFAULT NULL,
    `audit_at` DATETIME DEFAULT NULL,
    `remark` VARCHAR(255) DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_user_status` (`user_id`, `status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='提现申请';

-- ------------------------------ 4.4 社区 ------------------------------
CREATE TABLE IF NOT EXISTS `topic` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `name` VARCHAR(64) NOT NULL,
    `cover_url` VARCHAR(512) DEFAULT NULL,
    `description` VARCHAR(500) DEFAULT NULL,
    `sort_order` INT NOT NULL DEFAULT 0,
    `heat_score` INT NOT NULL DEFAULT 0,
    `status` TINYINT NOT NULL DEFAULT 1,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='话题';

CREATE TABLE IF NOT EXISTS `post` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `user_id` BIGINT NOT NULL,
    `content` TEXT DEFAULT NULL,
    `media_type` VARCHAR(20) NOT NULL DEFAULT 'image_text' COMMENT 'image_text/video',
    `media_urls_json` TEXT DEFAULT NULL,
    `media_cover_urls_json` TEXT DEFAULT NULL COMMENT '视频封面图 URL 列表 JSON',
    `topic_ids_json` VARCHAR(500) DEFAULT NULL,
    `tags_json` VARCHAR(500) DEFAULT NULL COMMENT '自定义标签名 JSON 数组',
    `location_code` VARCHAR(32) DEFAULT NULL,
    `visibility` TINYINT NOT NULL DEFAULT 1,
    `allow_comment` TINYINT NOT NULL DEFAULT 1 COMMENT '0禁止 1允许',
    `status` TINYINT NOT NULL DEFAULT 1,
    `like_count` INT NOT NULL DEFAULT 0,
    `comment_count` INT NOT NULL DEFAULT 0,
    `share_count` INT NOT NULL DEFAULT 0,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_user_id` (`user_id`),
    KEY `idx_created_at` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='帖子';

CREATE TABLE IF NOT EXISTS `post_like` (
    `user_id` BIGINT NOT NULL,
    `post_id` BIGINT NOT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`user_id`, `post_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='点赞';

CREATE TABLE IF NOT EXISTS `post_favorite` (
    `user_id` BIGINT NOT NULL,
    `post_id` BIGINT NOT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`user_id`, `post_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='收藏';

CREATE TABLE IF NOT EXISTS `comment` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `post_id` BIGINT NOT NULL,
    `user_id` BIGINT NOT NULL,
    `parent_id` BIGINT DEFAULT NULL COMMENT '楼中楼',
    `content` TEXT NOT NULL,
    `status` TINYINT NOT NULL DEFAULT 1,
    `like_count` INT NOT NULL DEFAULT 0,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_post_id` (`post_id`),
    KEY `idx_parent_id` (`parent_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='评论';

-- ------------------------------ 4.5 社交与 IM ------------------------------
CREATE TABLE IF NOT EXISTS `user_follow` (
    `user_id` BIGINT NOT NULL,
    `target_user_id` BIGINT NOT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`user_id`, `target_user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='关注关系';

CREATE TABLE IF NOT EXISTS `match_config` (
    `user_id` BIGINT NOT NULL,
    `gender` TINYINT DEFAULT NULL,
    `age_min` INT DEFAULT NULL,
    `age_max` INT DEFAULT NULL,
    `region_codes` VARCHAR(255) DEFAULT NULL,
    `xiyongshen_complement_level` INT DEFAULT NULL,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='匹配条件';

CREATE TABLE IF NOT EXISTS `chat_apply` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `from_user_id` BIGINT NOT NULL,
    `to_user_id` BIGINT NOT NULL,
    `status` VARCHAR(20) NOT NULL DEFAULT 'pending' COMMENT 'pending/approved/rejected',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='聊天申请';

CREATE TABLE IF NOT EXISTS `conversation` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `type` VARCHAR(20) NOT NULL COMMENT 'single/group',
    `name` VARCHAR(128) DEFAULT NULL COMMENT '群名',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_type` (`type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='会话';

CREATE TABLE IF NOT EXISTS `conversation_member` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `conversation_id` BIGINT NOT NULL,
    `user_id` BIGINT NOT NULL,
    `role` VARCHAR(20) DEFAULT 'member',
    `mute` TINYINT NOT NULL DEFAULT 0,
    `top` TINYINT NOT NULL DEFAULT 0,
    `last_read_msg_id` BIGINT DEFAULT NULL,
    `joined_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_conv_user` (`conversation_id`, `user_id`),
    KEY `idx_user_id` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='会话成员';

CREATE TABLE IF NOT EXISTS `message` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `conversation_id` BIGINT NOT NULL,
    `sender_id` BIGINT NOT NULL,
    `type` VARCHAR(20) NOT NULL COMMENT 'text/image/voice',
    `content_encrypted` TEXT DEFAULT NULL,
    `extra_json` TEXT DEFAULT NULL,
    `status` TINYINT NOT NULL DEFAULT 1,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_conv_created` (`conversation_id`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='消息';

CREATE TABLE IF NOT EXISTS `im_group` (
    `conversation_id` BIGINT NOT NULL,
    `owner_id` BIGINT NOT NULL,
    `max_members` INT NOT NULL DEFAULT 500,
    `is_public` TINYINT NOT NULL DEFAULT 0 COMMENT '0仅邀请 1可申请加入',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`conversation_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='群聊扩展';

CREATE TABLE IF NOT EXISTS `group_join_apply` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `user_id` BIGINT NOT NULL,
    `conversation_id` BIGINT NOT NULL,
    `status` VARCHAR(20) NOT NULL DEFAULT 'pending' COMMENT 'pending/approved/rejected',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_conv_status` (`conversation_id`, `status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='入群申请';

CREATE TABLE IF NOT EXISTS `teacher_apply` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `user_id` BIGINT NOT NULL,
    `real_name` VARCHAR(64) NOT NULL,
    `id_card_hash` VARCHAR(128) NOT NULL COMMENT '身份证号加密/哈希',
    `status` VARCHAR(20) NOT NULL DEFAULT 'pending' COMMENT 'pending/approved/rejected',
    `remark` VARCHAR(255) DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_user_status` (`user_id`, `status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='名师入驻申请';

-- ------------------------------ 4.5.1 互动通知 ------------------------------
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

-- ------------------------------ 4.6 举报与风控 ------------------------------
CREATE TABLE IF NOT EXISTS `report` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `reporter_id` BIGINT NOT NULL,
    `target_type` VARCHAR(20) NOT NULL COMMENT 'user/post/comment/message',
    `target_id` BIGINT NOT NULL,
    `reason` VARCHAR(255) DEFAULT NULL,
    `status` VARCHAR(20) NOT NULL DEFAULT 'pending',
    `handle_result` VARCHAR(255) DEFAULT NULL,
    `handled_by` BIGINT DEFAULT NULL,
    `handled_at` DATETIME DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_target` (`target_type`, `target_id`, `status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='举报记录';

CREATE TABLE IF NOT EXISTS `user_punish` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `user_id` BIGINT NOT NULL,
    `type` VARCHAR(20) NOT NULL COMMENT 'warning/mute/ban',
    `reason` VARCHAR(255) DEFAULT NULL,
    `expire_at` DATETIME DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_user_expire` (`user_id`, `expire_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户处罚';

-- ------------------------------ 4.7 系统与运营 ------------------------------
CREATE TABLE IF NOT EXISTS `sys_config` (
    `config_key` VARCHAR(64) NOT NULL,
    `config_value` TEXT DEFAULT NULL,
    `remark` VARCHAR(255) DEFAULT NULL,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`config_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='系统配置';

CREATE TABLE IF NOT EXISTS `banner` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `type` VARCHAR(20) NOT NULL COMMENT 'home/splash',
    `image_url` VARCHAR(512) NOT NULL,
    `link_url` VARCHAR(512) DEFAULT NULL,
    `sort_order` INT NOT NULL DEFAULT 0,
    `status` TINYINT NOT NULL DEFAULT 1,
    `start_at` DATETIME DEFAULT NULL,
    `end_at` DATETIME DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='轮播图/开屏';

CREATE TABLE IF NOT EXISTS `announcement` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `title` VARCHAR(128) NOT NULL COMMENT '标题',
    `content` TEXT DEFAULT NULL COMMENT '正文',
    `link_url` VARCHAR(512) DEFAULT NULL COMMENT '可选跳转链接',
    `status` TINYINT NOT NULL DEFAULT 1 COMMENT '0下架 1展示',
    `sort_order` INT NOT NULL DEFAULT 0 COMMENT '排序，越大越靠前',
    `start_at` DATETIME DEFAULT NULL,
    `end_at` DATETIME DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_status_time` (`status`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='后台公告';

CREATE TABLE IF NOT EXISTS `agreement` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `type` VARCHAR(32) NOT NULL COMMENT 'privacy/user_agreement',
    `title` VARCHAR(128) NOT NULL,
    `content` LONGTEXT DEFAULT NULL,
    `version` VARCHAR(20) DEFAULT NULL,
    `effective_at` DATETIME DEFAULT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='协议版本';

-- =============================================================================
-- 初始化完成
-- =============================================================================
