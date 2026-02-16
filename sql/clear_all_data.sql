-- 清空业务库所有数据（不删表结构）
-- 执行：mysql -u root -p lingshu < sql/clear_all_data.sql
-- 或：mysql -u root -p lingshu -e "source /path/to/server/sql/clear_all_data.sql"

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- 账户与用户
TRUNCATE TABLE wallet_log;
TRUNCATE TABLE login_device;
TRUNCATE TABLE user_wallet;
TRUNCATE TABLE order_main;
TRUNCATE TABLE withdraw_apply;
TRUNCATE TABLE user_profile;
TRUNCATE TABLE user_bazi;
TRUNCATE TABLE bazi_report;
TRUNCATE TABLE fengshui_record;
TRUNCATE TABLE hepan_record;
TRUNCATE TABLE `user`;

-- 社区
TRUNCATE TABLE comment;
TRUNCATE TABLE post_like;
TRUNCATE TABLE post_favorite;
TRUNCATE TABLE post;
TRUNCATE TABLE topic;

-- 社交与 IM
TRUNCATE TABLE user_follow;
TRUNCATE TABLE match_config;
TRUNCATE TABLE chat_apply;
TRUNCATE TABLE message;
TRUNCATE TABLE conversation_member;
TRUNCATE TABLE im_group;
TRUNCATE TABLE conversation;
TRUNCATE TABLE notification;

-- 举报与风控
TRUNCATE TABLE report;
TRUNCATE TABLE user_punish;

-- 系统与运营
TRUNCATE TABLE sys_config;
TRUNCATE TABLE banner;
TRUNCATE TABLE agreement;

-- 迁移表（若未执行过 migrate_group_public / migrate_teacher，请注释下面两行）
TRUNCATE TABLE group_join_apply;
TRUNCATE TABLE teacher_apply;

SET FOREIGN_KEY_CHECKS = 1;
