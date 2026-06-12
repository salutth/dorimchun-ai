-- RiverWatch Supabase 테이블 생성 SQL
-- Supabase 대시보드 > SQL Editor 에서 실행

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

-- 2. 생물 관찰 데이터 (iNaturalist + 시민 제보)
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

-- 5. 인덱스
create index idx_readings_river on river_readings(river);
create index idx_readings_measured on river_readings(measured_at);
create index idx_species_river on species_observations(river);
create index idx_species_taxon on species_observations(taxon_name);
create index idx_species_invasive on species_observations(is_invasive);
