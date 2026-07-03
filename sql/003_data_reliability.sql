-- 003: 데이터 신뢰성 강화 — UNIQUE 제약조건 추가 (2026-07-04)
-- flood_predictions, flood_alerts, flood_risk_index 테이블 중복 방지

-- 1. flood_predictions: 같은 관측소+예측시각+예측시간 중복 방지
ALTER TABLE flood_predictions
  ADD CONSTRAINT uq_flood_predictions_station_predicted
  UNIQUE (station, predicted_at, prediction_hour);

-- 2. flood_alerts: 같은 관측소+발령시각 중복 방지
ALTER TABLE flood_alerts
  ADD CONSTRAINT uq_flood_alerts_station_issued
  UNIQUE (station, issued_at);

-- 3. flood_risk_index: 같은 관측소+산출시각 중복 방지
ALTER TABLE flood_risk_index
  ADD CONSTRAINT uq_flood_risk_index_station_calc
  UNIQUE (station, calculated_at);

-- 4. river_readings에 collected_at 컬럼 추가 (수집 시각 기록용)
ALTER TABLE river_readings
  ADD COLUMN IF NOT EXISTS collected_at timestamptz;

-- 5. 기존 중복 데이터 정리 (각 테이블에서 중복 중 최신 1건만 유지)
-- flood_predictions
DELETE FROM flood_predictions a
  USING flood_predictions b
  WHERE a.id < b.id
    AND a.station = b.station
    AND a.predicted_at = b.predicted_at
    AND a.prediction_hour = b.prediction_hour;

-- flood_alerts
DELETE FROM flood_alerts a
  USING flood_alerts b
  WHERE a.id < b.id
    AND a.station = b.station
    AND a.issued_at = b.issued_at;

-- flood_risk_index (있는 경우)
DELETE FROM flood_risk_index a
  USING flood_risk_index b
  WHERE a.id < b.id
    AND a.station = b.station
    AND a.calculated_at = b.calculated_at;
