-- ============================================
-- 통합 테이블 생성 SQL — 거시기-시민과학 프로젝트
-- Supabase SQL Editor에서 한 번에 실행
-- 2026-07-03
-- ============================================

-- =====================
-- PART 1: RiverWatch 테이블
-- =====================

-- 1. 하천 수위 데이터
create table river_readings (
  id bigint generated always as identity primary key,
  station text not null,
  river text not null,
  gu text,
  water_level real,
  embankment_height real,
  level_ratio real,
  status text,
  measured_at timestamptz,
  collected_at timestamptz default now()
);

alter table river_readings enable row level security;
create policy "river_readings_read" on river_readings for select using (true);
create policy "river_readings_insert" on river_readings for insert with check (true);

-- 2. 생물 관찰 데이터
create table species_observations (
  id bigint generated always as identity primary key,
  taxon_name text,
  common_name text,
  korean_name text,
  taxon_id int,
  confidence real,
  latitude real,
  longitude real,
  river text,
  photo_url text,
  observer text,
  source text default 'inaturalist',
  is_invasive boolean default false,
  inaturalist_id bigint,
  observed_at timestamptz,
  collected_at timestamptz default now()
);

alter table species_observations enable row level security;
create policy "species_read" on species_observations for select using (true);
create policy "species_insert" on species_observations for insert with check (true);

-- 3. 외래종 경보
create table invasive_alerts (
  id bigint generated always as identity primary key,
  observation_id bigint references species_observations(id),
  species_name text not null,
  alert_level text default 'warning',
  river text,
  latitude real,
  longitude real,
  notified boolean default false,
  created_at timestamptz default now()
);

alter table invasive_alerts enable row level security;
create policy "alerts_read" on invasive_alerts for select using (true);
create policy "alerts_insert" on invasive_alerts for insert with check (true);

-- 4. EHI 생태건강성지수
create table ehi_scores (
  id bigint generated always as identity primary key,
  river text not null,
  biodiversity_score real,
  water_stability_score real,
  non_invasive_score real,
  observation_freq_score real,
  ehi_score real,
  grade text,
  species_count int,
  reading_count int,
  calculated_at timestamptz default now()
);

alter table ehi_scores enable row level security;
create policy "ehi_read" on ehi_scores for select using (true);
create policy "ehi_insert" on ehi_scores for insert with check (true);

-- 5. 헬스체크 테이블
create table collector_health (
  id bigint generated always as identity primary key,
  collector text not null,
  status text not null default 'ok',
  record_count int default 0,
  error_message text,
  collected_at timestamptz default now()
);

alter table collector_health enable row level security;
create policy "health_read" on collector_health for select using (true);
create policy "health_insert" on collector_health for insert with check (true);

-- 6. 문화재 데이터 (하천ON)
create table if not exists cultural_assets (
  id bigint generated always as identity primary key,
  name text not null,
  name_hanja text,
  category text,
  type text,
  era text,
  address text,
  latitude real,
  longitude real,
  river text,
  image_url text,
  description text,
  designation_date date,
  collected_at timestamptz default now()
);

alter table cultural_assets enable row level security;
create policy "cultural_read" on cultural_assets for select using (true);
create policy "cultural_insert" on cultural_assets for insert with check (true);

-- 7. 기상 예보
create table if not exists weather_forecasts (
  id bigint generated always as identity primary key,
  region text not null,
  forecast_date date,
  temperature real,
  precipitation real,
  humidity real,
  wind_speed real,
  weather_condition text,
  collected_at timestamptz default now()
);

alter table weather_forecasts enable row level security;
create policy "weather_read" on weather_forecasts for select using (true);
create policy "weather_insert" on weather_forecasts for insert with check (true);

-- 8. 홍수 경보
create table if not exists flood_alerts (
  id bigint generated always as identity primary key,
  river text not null,
  station text,
  alert_level text,
  water_level real,
  threshold real,
  message text,
  issued_at timestamptz,
  collected_at timestamptz default now()
);

alter table flood_alerts enable row level security;
create policy "flood_read" on flood_alerts for select using (true);
create policy "flood_insert" on flood_alerts for insert with check (true);

-- 9. AI 침수 예측 (Phase 3-1 LSTM)
create table flood_predictions (
  id bigint generated always as identity primary key,
  station text not null,
  river text not null,
  prediction_hour int not null,
  predicted_level real not null,
  predicted_ratio real,
  predicted_status text,
  confidence real,
  model_version text default 'v1',
  input_snapshot jsonb,
  predicted_at timestamptz not null,
  target_time timestamptz not null,
  created_at timestamptz default now()
);

alter table flood_predictions enable row level security;
create policy "predictions_read" on flood_predictions for select using (true);
create policy "predictions_insert" on flood_predictions for insert with check (true);

-- 인덱스
create index idx_readings_river on river_readings(river);
create index idx_readings_measured on river_readings(measured_at);
create index idx_species_river on species_observations(river);
create index idx_species_taxon on species_observations(taxon_name);
create index idx_species_invasive on species_observations(is_invasive);
create unique index uq_species_inat_id on species_observations(inaturalist_id) where inaturalist_id is not null;
alter table river_readings add constraint uq_readings_station_time unique (station, measured_at);
create index idx_predictions_station_target on flood_predictions(station, target_time);
create index idx_predictions_river on flood_predictions(river);
create index idx_predictions_created on flood_predictions(created_at desc);
alter table flood_predictions add constraint uq_predictions unique (station, target_time, predicted_at);

-- =====================
-- PART 2: 거시기(Geosigi) 테이블
-- =====================

CREATE TABLE geosigi_users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  nationality VARCHAR(50),
  languages TEXT[] DEFAULT '{}',
  interest_tags TEXT[] DEFAULT '{}',
  preferred_lang VARCHAR(5) DEFAULT 'en',
  consent_at TIMESTAMPTZ,
  consent_version VARCHAR(20),
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE geosigi_missions (
  id SERIAL PRIMARY KEY,
  title_ko VARCHAR(200) NOT NULL,
  title_en VARCHAR(200),
  description_ko TEXT,
  description_en TEXT,
  mission_type VARCHAR(50) NOT NULL,
  river VARCHAR(50),
  location_lat DOUBLE PRECISION,
  location_lng DOUBLE PRECISION,
  status VARCHAR(20) DEFAULT 'active',
  start_date DATE,
  end_date DATE,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE geosigi_mission_logs (
  id SERIAL PRIMARY KEY,
  mission_id INT REFERENCES geosigi_missions(id),
  user_id UUID REFERENCES geosigi_users(id),
  data JSONB DEFAULT '{}',
  photo_url TEXT,
  latitude DOUBLE PRECISION,
  longitude DOUBLE PRECISION,
  completed_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE geosigi_posts (
  id SERIAL PRIMARY KEY,
  user_id UUID REFERENCES geosigi_users(id),
  content TEXT NOT NULL,
  lang VARCHAR(5) DEFAULT 'ko',
  post_type VARCHAR(30) DEFAULT 'general',
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE geosigi_stories (
  id SERIAL PRIMARY KEY,
  user_id UUID REFERENCES geosigi_users(id),
  title VARCHAR(300),
  body TEXT,
  lang VARCHAR(5) DEFAULT 'ko',
  activity_type VARCHAR(50),
  shared BOOLEAN DEFAULT false,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE geosigi_consent_logs (
  id SERIAL PRIMARY KEY,
  user_id UUID REFERENCES geosigi_users(id),
  consent_type VARCHAR(50) NOT NULL,
  agreed BOOLEAN NOT NULL,
  version VARCHAR(20) NOT NULL,
  ip_hash VARCHAR(64),
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE geosigi_guides (
  id SERIAL PRIMARY KEY,
  category VARCHAR(50) NOT NULL,
  title_ko VARCHAR(300),
  title_en VARCHAR(300),
  content_ko TEXT,
  content_en TEXT,
  source_url TEXT,
  source_name VARCHAR(100),
  is_verified BOOLEAN DEFAULT false,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE geosigi_trusted_sources (
  id SERIAL PRIMARY KEY,
  name_ko VARCHAR(200) NOT NULL,
  name_en VARCHAR(200),
  category VARCHAR(50),
  url TEXT,
  phone VARCHAR(30),
  description_ko TEXT,
  description_en TEXT,
  is_official BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- 거시기 RLS
ALTER TABLE geosigi_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE geosigi_missions ENABLE ROW LEVEL SECURITY;
ALTER TABLE geosigi_mission_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE geosigi_posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE geosigi_stories ENABLE ROW LEVEL SECURITY;
ALTER TABLE geosigi_consent_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE geosigi_guides ENABLE ROW LEVEL SECURITY;
ALTER TABLE geosigi_trusted_sources ENABLE ROW LEVEL SECURITY;

CREATE POLICY "geosigi_read_all" ON geosigi_missions FOR SELECT USING (true);
CREATE POLICY "geosigi_read_guides" ON geosigi_guides FOR SELECT USING (true);
CREATE POLICY "geosigi_read_trusted" ON geosigi_trusted_sources FOR SELECT USING (true);
CREATE POLICY "geosigi_read_posts" ON geosigi_posts FOR SELECT USING (true);
CREATE POLICY "geosigi_read_stories" ON geosigi_stories FOR SELECT USING (true);

CREATE POLICY "geosigi_insert_users" ON geosigi_users FOR INSERT WITH CHECK (true);
CREATE POLICY "geosigi_insert_logs" ON geosigi_mission_logs FOR INSERT WITH CHECK (true);
CREATE POLICY "geosigi_insert_posts" ON geosigi_posts FOR INSERT WITH CHECK (true);
CREATE POLICY "geosigi_insert_stories" ON geosigi_stories FOR INSERT WITH CHECK (true);
CREATE POLICY "geosigi_insert_consent" ON geosigi_consent_logs FOR INSERT WITH CHECK (true);

-- 거시기 초기 데이터
INSERT INTO geosigi_missions (title_ko, title_en, mission_type, river, status) VALUES
  ('도림천 수질 측정', 'Dorimcheon Water Quality', 'water_quality', '도림천', 'active'),
  ('안양천 생물 관찰', 'Anyangcheon Species Observation', 'species_observation', '안양천', 'active'),
  ('청계천 수질 측정', 'Cheonggyecheon Water Quality', 'water_quality', '청계천', 'active'),
  ('중랑천 생태교란종 모니터링', 'Jungnangcheon Invasive Species', 'species_observation', '중랑천', 'active'),
  ('탄천 수질 측정', 'Tancheon Water Quality', 'water_quality', '탄천', 'active');

INSERT INTO geosigi_trusted_sources (name_ko, name_en, category, url, phone, description_ko, description_en) VALUES
  ('외국인종합안내센터', 'Foreigner Help Center', 'immigration', 'https://www.hikorea.go.kr', '1345', '비자·체류·생활 상담', 'Visa, residence, and daily life consultation'),
  ('Hi Korea 출입국외국인청', 'Hi Korea Immigration', 'immigration', 'https://www.immigration.go.kr', '1345', '출입국 관련 공식 정보', 'Official immigration information'),
  ('국립국제교육원 NIIED', 'NIIED', 'education', 'https://www.niied.go.kr', '02-3668-1300', 'GKS 장학금·교환학생 정보', 'GKS scholarship and exchange programs'),
  ('건강보험심사평가원', 'HIRA', 'health', 'https://www.hira.or.kr', '1644-2000', '외국어 가능 의료기관 검색', 'Search for multilingual medical facilities'),
  ('경찰청 외국인 도움센터', 'Police Foreign Help', 'emergency', 'https://www.police.go.kr', '112', '긴급 신고·범죄 피해', 'Emergency reports and crime victim support');
