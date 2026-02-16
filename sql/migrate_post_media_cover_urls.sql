-- 帖子视频封面图 URL 列表（JSON），与 media_urls_json 一一对应；仅视频帖使用
-- 执行：mysql -u root -p lingshu < migrate_post_media_cover_urls.sql

ALTER TABLE post ADD COLUMN media_cover_urls_json TEXT DEFAULT NULL COMMENT '视频封面图 URL 列表 JSON';
