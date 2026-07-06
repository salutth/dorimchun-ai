-- 004: water_quality 테이블 생성 (2026-07-06)
-- 서울시 수질 TMS API(WPOSInformationTime) 데이터 저장용

CREATE TABLE IF NOT EXISTS water_quality (
  id bigint generated always as identity primary key,
  station_name text not null,
  ph real,
  dissolved_oxygen real,
  water_temp real,
  total_nitrogen real,
  total_phosphorus real,
  toc real,
  phenol real,
  cyanide real,
  do_grade text,
  measured_at timestamptz not null,
  collected_at timestamptz default now()
);

ALTER TABLE water_quality ENABLE ROW LEVEL SECURITY;

CREATE POLICY "wq_read" ON water_quality FOR SELECT USING (true);
CREATE POLICY "wq_insert" ON water_quality FOR INSERT WITH CHECK (true);

ALTER TABLE water_quality
  ADD CONSTRAINT uq_wq_station_measured
  UNIQUE (station_name, measured_at);

CREATE INDEX idx_wq_station ON water_quality(station_name);
CREATE INDEX idx_wq_measured ON water_quality(measured_at DESC);
