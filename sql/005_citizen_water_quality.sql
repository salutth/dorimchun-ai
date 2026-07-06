-- 005: citizen_water_quality 테이블 생성 (2026-07-06)
-- 시민 현장 수질 측정 데이터 (dashboard.html 시민 측정 탭)

CREATE TABLE IF NOT EXISTS citizen_water_quality (
  id bigint generated always as identity primary key,
  river text not null,
  observer text default '시민과학자',
  latitude double precision,
  longitude double precision,
  photo_data text,
  ph real,
  dissolved_oxygen real,
  water_temp real,
  turbidity real,
  conductivity real,
  bod real,
  cod real,
  ss real,
  water_color text,
  smell text,
  flow_speed text,
  trash_level text,
  weather text,
  air_temp real,
  humidity real,
  recent_rain text,
  do_grade text,
  memo text,
  measured_at timestamptz not null,
  created_at timestamptz default now()
);

ALTER TABLE citizen_water_quality ENABLE ROW LEVEL SECURITY;

CREATE POLICY "cwq_read" ON citizen_water_quality FOR SELECT USING (true);
CREATE POLICY "cwq_insert" ON citizen_water_quality FOR INSERT WITH CHECK (true);

CREATE INDEX idx_cwq_river ON citizen_water_quality(river);
CREATE INDEX idx_cwq_measured ON citizen_water_quality(measured_at DESC);
