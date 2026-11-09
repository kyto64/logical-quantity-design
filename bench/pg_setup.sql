-- 計測用スキーマとダミーデータ（PostgreSQL）
-- status: 0=none, 1=before, 2=completed（Rails の integer enum を想定）
DROP TABLE IF EXISTS purchase_item, delivery_item, inventory;

CREATE TABLE inventory (
  id bigint PRIMARY KEY,
  company_id bigint NOT NULL,
  quantity numeric(15,3) NOT NULL
);
CREATE TABLE purchase_item (
  id bigserial PRIMARY KEY,
  company_id bigint NOT NULL,
  purchase_id bigint NOT NULL,
  inventory_id bigint NOT NULL,
  status smallint NOT NULL,
  scheduled_date date,
  completed_date date,
  quantity numeric(15,3) NOT NULL
);
CREATE TABLE delivery_item (LIKE purchase_item INCLUDING ALL);
ALTER TABLE delivery_item RENAME COLUMN purchase_id TO delivery_id;

SELECT setseed(0.42);

-- 対象アカウント(company_id=1)：在庫20万件。別アカウント(company_id=2)：在庫5万件（他テナントの混在）
INSERT INTO inventory
SELECT g, 1, (random()*1000)::int FROM generate_series(1, 200000) g;
INSERT INTO inventory
SELECT 200000 + g, 2, (random()*1000)::int FROM generate_series(1, 50000) g;

-- 最悪ケースの在庫：1ページ目(id 1〜50)と最終ページ(id 199951〜200000)
-- 各在庫に、入庫・出庫それぞれ1,000件、すべて未完了。予定日は今日〜365日後に分散、うち10%はNULL
CREATE TEMP TABLE heavy AS
SELECT id FROM inventory WHERE company_id = 1 AND (id <= 50 OR id > 199950);

INSERT INTO purchase_item (company_id, purchase_id, inventory_id, status, scheduled_date, quantity)
SELECT 1, (random()*1000000)::int, h.id, (random())::int,
       CASE WHEN random() < 0.1 THEN NULL ELSE DATE '2026-11-16' + (random()*365)::int END,
       (random()*100)::int + 1
FROM heavy h, generate_series(1, 1000);
INSERT INTO delivery_item (company_id, delivery_id, inventory_id, status, scheduled_date, quantity)
SELECT 1, (random()*1000000)::int, h.id, (random())::int,
       CASE WHEN random() < 0.1 THEN NULL ELSE DATE '2026-11-16' + (random()*365)::int END,
       (random()*100)::int + 1
FROM heavy h, generate_series(1, 1000);

-- それ以外の在庫：入庫・出庫それぞれ5件。70%は completed（過去日付）、30%は未完了
INSERT INTO purchase_item (company_id, purchase_id, inventory_id, status, scheduled_date, completed_date, quantity)
SELECT i.company_id, (random()*1000000)::int, i.id, s.st,
       CASE WHEN s.st = 2 THEN DATE '2026-11-16' - (random()*365)::int
            WHEN random() < 0.1 THEN NULL
            ELSE DATE '2026-11-16' + (random()*90)::int END,
       CASE WHEN s.st = 2 THEN DATE '2026-11-16' - (random()*365)::int END,
       (random()*100)::int + 1
FROM inventory i
CROSS JOIN generate_series(1, 5) g
CROSS JOIN LATERAL (SELECT CASE WHEN random() < 0.7 THEN 2 ELSE (random())::int END AS st, g) s
WHERE NOT EXISTS (SELECT 1 FROM heavy h WHERE h.id = i.id);
INSERT INTO delivery_item (company_id, delivery_id, inventory_id, status, scheduled_date, completed_date, quantity)
SELECT i.company_id, (random()*1000000)::int, i.id, s.st,
       CASE WHEN s.st = 2 THEN DATE '2026-11-16' - (random()*365)::int
            WHEN random() < 0.1 THEN NULL
            ELSE DATE '2026-11-16' + (random()*90)::int END,
       CASE WHEN s.st = 2 THEN DATE '2026-11-16' - (random()*365)::int END,
       (random()*100)::int + 1
FROM inventory i
CROSS JOIN generate_series(1, 5) g
CROSS JOIN LATERAL (SELECT CASE WHEN random() < 0.7 THEN 2 ELSE (random())::int END AS st, g) s
WHERE NOT EXISTS (SELECT 1 FROM heavy h WHERE h.id = i.id);

-- 設計資料 3.4 のインデックス
CREATE INDEX idx_inventory_company_id ON inventory (company_id, id);
CREATE INDEX idx_pi_pending ON purchase_item (company_id, inventory_id, status, scheduled_date, quantity);
CREATE INDEX idx_di_pending ON delivery_item (company_id, inventory_id, status, scheduled_date, quantity);

-- 比較用：事前集計（在庫×日付の増減）。出庫の NULL は 1970-01-01、入庫の NULL は除外
CREATE TABLE scheduled_quantity_deltas AS
SELECT company_id, inventory_id, d AS date, SUM(q) AS delta FROM (
  SELECT company_id, inventory_id, scheduled_date AS d, quantity AS q
  FROM purchase_item WHERE status IN (0,1) AND scheduled_date IS NOT NULL
  UNION ALL
  SELECT company_id, inventory_id, COALESCE(scheduled_date, DATE '1970-01-01'), -quantity
  FROM delivery_item WHERE status IN (0,1)
) x GROUP BY company_id, inventory_id, d;
CREATE UNIQUE INDEX idx_deltas ON scheduled_quantity_deltas (company_id, inventory_id, date) INCLUDE (delta);

VACUUM ANALYZE;

SELECT 'inventory' t, count(*) FROM inventory
UNION ALL SELECT 'purchase_item', count(*) FROM purchase_item
UNION ALL SELECT 'delivery_item', count(*) FROM delivery_item
UNION ALL SELECT 'deltas', count(*) FROM scheduled_quantity_deltas;
