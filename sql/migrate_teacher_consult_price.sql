-- 名师咨询单价：后台可配置，默认 10 元
-- 执行：mysql -u root -p your_db < migrate_teacher_consult_price.sql

ALTER TABLE user_profile
  ADD COLUMN consult_price DECIMAL(10,2) NOT NULL DEFAULT 10.00
  COMMENT '名师咨询单价（元）' AFTER is_master;
