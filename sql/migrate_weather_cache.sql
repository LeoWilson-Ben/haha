-- 天气按天缓存：同一城市同一天只请求一次天气接口，结果存库
CREATE TABLE IF NOT EXISTS weather_cache (
  cache_date DATE NOT NULL COMMENT '缓存日期',
  city VARCHAR(64) NOT NULL COMMENT '城市（如 武汉）',
  weather VARCHAR(64) NOT NULL DEFAULT '' COMMENT '天气描述',
  temperature FLOAT NULL COMMENT '温度 °C',
  weather_city VARCHAR(64) NOT NULL DEFAULT '' COMMENT '展示用城市名（如 武汉市）',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (cache_date, city)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='天气按日缓存';
