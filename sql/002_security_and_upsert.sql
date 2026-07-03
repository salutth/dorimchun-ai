-- RiverWatch 보안 강화 + UPSERT 유니크 제약조건
-- Supabase SQL Editor에서 실행 (2026-07-03)
-- ============================================================

-- ============================================================
-- PART 1: UNIQUE 제약조건 (중복 삽입 방지)
-- ============================================================

-- river_readings: 관측소+측정시각 기준 중복 방지
ALTER TABLE river_readings
  ADD CONSTRAINT uq_river_readings_station_time
  UNIQUE (station, measured_at);

-- species_observations: 종+하천+관찰일 기준 중복 방지
ALTER TABLE species_observations
  ADD CONSTRAINT uq_species_obs_taxon_river_date
  UNIQUE (taxon_name, river, observed_at);

-- weather_forecasts: 지역+예보일+상태(시간포함) 기준 중복 방지
ALTER TABLE weather_forecasts
  ADD CONSTRAINT uq_weather_region_date_cond
  UNIQUE (region, forecast_date, weather_condition);

-- cultural_assets: 이름+하천 기준 중복 방지
ALTER TABLE cultural_assets
  ADD CONSTRAINT uq_cultural_assets_name_river
  UNIQUE (name, river);

-- ehi_scores: 하천별 1시간 이내 중복 방지
ALTER TABLE ehi_scores
  ADD CONSTRAINT uq_ehi_river_time
  UNIQUE (river, collected_at);

-- ============================================================
-- PART 2: RLS 정책 강화 (RiverWatch 테이블)
-- ============================================================

-- RiverWatch 테이블 RLS 활성화 (이미 활성이면 무시)
ALTER TABLE river_readings ENABLE ROW LEVEL SECURITY;
ALTER TABLE species_observations ENABLE ROW LEVEL SECURITY;
ALTER TABLE ehi_scores ENABLE ROW LEVEL SECURITY;
ALTER TABLE cultural_assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE weather_forecasts ENABLE ROW LEVEL SECURITY;
ALTER TABLE flood_alerts ENABLE ROW LEVEL SECURITY;
ALTER TABLE flood_predictions ENABLE ROW LEVEL SECURITY;
ALTER TABLE invasive_alerts ENABLE ROW LEVEL SECURITY;
ALTER TABLE collector_health ENABLE ROW LEVEL SECURITY;

-- SELECT: 공개 읽기 (anon 허용)
DO $$ BEGIN
  -- river_readings
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='river_readings' AND policyname='rw_select_all') THEN
    CREATE POLICY rw_select_all ON river_readings FOR SELECT USING (true);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='species_observations' AND policyname='sp_select_all') THEN
    CREATE POLICY sp_select_all ON species_observations FOR SELECT USING (true);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='ehi_scores' AND policyname='ehi_select_all') THEN
    CREATE POLICY ehi_select_all ON ehi_scores FOR SELECT USING (true);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='cultural_assets' AND policyname='ca_select_all') THEN
    CREATE POLICY ca_select_all ON cultural_assets FOR SELECT USING (true);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='weather_forecasts' AND policyname='wf_select_all') THEN
    CREATE POLICY wf_select_all ON weather_forecasts FOR SELECT USING (true);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='flood_alerts' AND policyname='fa_select_all') THEN
    CREATE POLICY fa_select_all ON flood_alerts FOR SELECT USING (true);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='flood_predictions' AND policyname='fp_select_all') THEN
    CREATE POLICY fp_select_all ON flood_predictions FOR SELECT USING (true);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='invasive_alerts' AND policyname='ia_select_all') THEN
    CREATE POLICY ia_select_all ON invasive_alerts FOR SELECT USING (true);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='collector_health' AND policyname='ch_select_all') THEN
    CREATE POLICY ch_select_all ON collector_health FOR SELECT USING (true);
  END IF;
END $$;

-- INSERT: anon 차단 — service_role(수집기)만 쓰기 가능
-- service_role은 RLS를 우회하므로, 이 정책은 anon/authenticated 사용자에게만 적용
-- 기존 "모두 허용" INSERT 정책 제거 후 재생성

-- RiverWatch 테이블: INSERT 금지 (service_role만 가능)
DO $$
DECLARE
  tbl TEXT;
  pol RECORD;
BEGIN
  FOR tbl IN SELECT unnest(ARRAY[
    'river_readings','species_observations','ehi_scores',
    'cultural_assets','weather_forecasts','flood_alerts',
    'flood_predictions','invasive_alerts','collector_health'
  ]) LOOP
    FOR pol IN SELECT policyname FROM pg_policies WHERE tablename = tbl AND cmd = 'INSERT' LOOP
      EXECUTE format('DROP POLICY %I ON %I', pol.policyname, tbl);
    END LOOP;
    EXECUTE format(
      'CREATE POLICY %I ON %I FOR INSERT WITH CHECK (false)',
      tbl || '_insert_deny_anon', tbl
    );
  END LOOP;
END $$;

-- ============================================================
-- PART 3: Geosigi RLS 강화
-- ============================================================

-- 기존 INSERT 정책 제거 후 인증 사용자만 허용으로 재생성
DROP POLICY IF EXISTS "geosigi_insert_users" ON geosigi_users;
DROP POLICY IF EXISTS "geosigi_insert_logs" ON geosigi_mission_logs;
DROP POLICY IF EXISTS "geosigi_insert_posts" ON geosigi_posts;
DROP POLICY IF EXISTS "geosigi_insert_stories" ON geosigi_stories;
DROP POLICY IF EXISTS "geosigi_insert_consent" ON geosigi_consent_logs;

CREATE POLICY "geosigi_insert_users" ON geosigi_users
  FOR INSERT WITH CHECK (auth.uid() IS NOT NULL);
CREATE POLICY "geosigi_insert_logs" ON geosigi_mission_logs
  FOR INSERT WITH CHECK (auth.uid() IS NOT NULL);
CREATE POLICY "geosigi_insert_posts" ON geosigi_posts
  FOR INSERT WITH CHECK (auth.uid() IS NOT NULL);
CREATE POLICY "geosigi_insert_stories" ON geosigi_stories
  FOR INSERT WITH CHECK (auth.uid() IS NOT NULL);
CREATE POLICY "geosigi_insert_consent" ON geosigi_consent_logs
  FOR INSERT WITH CHECK (auth.uid() IS NOT NULL);

-- ============================================================
-- PART 4: 기존 중복 데이터 정리 (유니크 제약조건 적용 전 필요시)
-- ============================================================

-- 중복 제거: weather_forecasts (가장 최신 collected_at만 보존)
DELETE FROM weather_forecasts a
  USING weather_forecasts b
  WHERE a.id < b.id
    AND a.region = b.region
    AND a.forecast_date = b.forecast_date
    AND a.weather_condition = b.weather_condition;

-- 중복 제거: species_observations
DELETE FROM species_observations a
  USING species_observations b
  WHERE a.id < b.id
    AND a.taxon_name = b.taxon_name
    AND a.river = b.river
    AND a.observed_at = b.observed_at;

-- 중복 제거: cultural_assets
DELETE FROM cultural_assets a
  USING cultural_assets b
  WHERE a.id < b.id
    AND a.name = b.name
    AND a.river = b.river;

-- 중복 제거: ehi_scores
DELETE FROM ehi_scores a
  USING ehi_scores b
  WHERE a.id < b.id
    AND a.river = b.river
    AND a.collected_at = b.collected_at;
