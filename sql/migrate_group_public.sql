-- 可加入群聊：im_group 增加 is_public，新增 group_join_apply 表
-- 执行：mysql -u root -p lingshu < migrate_group_public.sql

ALTER TABLE im_group ADD COLUMN is_public TINYINT NOT NULL DEFAULT 0 COMMENT '0仅邀请 1可申请加入';

CREATE TABLE IF NOT EXISTS group_join_apply (
    id BIGINT NOT NULL AUTO_INCREMENT,
    user_id BIGINT NOT NULL,
    conversation_id BIGINT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending' COMMENT 'pending/approved/rejected',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_conv_status (conversation_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='入群申请';
