-- 名师相关：用户名师标识、名师入驻申请表
-- 执行：mysql -u root -p lingshu < migrate_teacher.sql

ALTER TABLE user_profile ADD COLUMN is_master TINYINT NOT NULL DEFAULT 0 COMMENT '0否 1是名师';
ALTER TABLE user_profile ADD COLUMN real_name VARCHAR(64) DEFAULT NULL COMMENT '实名';
ALTER TABLE user_profile ADD COLUMN id_card_hash VARCHAR(128) DEFAULT NULL COMMENT '身份证号哈希';

CREATE TABLE IF NOT EXISTS teacher_apply (
    id BIGINT NOT NULL AUTO_INCREMENT,
    user_id BIGINT NOT NULL,
    real_name VARCHAR(64) NOT NULL,
    id_card_hash VARCHAR(128) NOT NULL COMMENT '身份证号加密/哈希',
    status VARCHAR(20) NOT NULL DEFAULT 'pending' COMMENT 'pending/approved/rejected',
    remark VARCHAR(255) DEFAULT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_user_status (user_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='名师入驻申请';
