-- 帖子评论权限：0禁止评论 1允许评论
-- 执行：mysql -u root -p lingshu < migrate_post_allow_comment.sql

ALTER TABLE post ADD COLUMN allow_comment TINYINT NOT NULL DEFAULT 1 COMMENT '0禁止 1允许';
