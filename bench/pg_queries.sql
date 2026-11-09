-- psql -v offset=... -v inv=... で実行
\set date '''2027-12-31'''
\set from '''2026-11-16'''
\set to '''2027-02-14'''

\echo '=== [直接集計] 一覧 ==='
EXPLAIN (ANALYZE, BUFFERS)
WITH target AS (
  SELECT id, quantity FROM inventory
  WHERE company_id = 1 ORDER BY id LIMIT 50 OFFSET :offset
),
pending AS (
  SELECT pi.inventory_id, pi.quantity AS qty
  FROM target t JOIN purchase_item pi ON pi.company_id = 1 AND pi.inventory_id = t.id
  WHERE pi.status IN (0, 1) AND pi.scheduled_date <= :date
  UNION ALL
  SELECT di.inventory_id, -di.quantity
  FROM target t JOIN delivery_item di ON di.company_id = 1 AND di.inventory_id = t.id
  WHERE di.status IN (0, 1) AND (di.scheduled_date <= :date OR di.scheduled_date IS NULL)
)
SELECT t.id, t.quantity, t.quantity + COALESCE(SUM(p.qty), 0) AS logical_quantity
FROM target t LEFT JOIN pending p ON p.inventory_id = t.id
GROUP BY t.id, t.quantity ORDER BY t.id;

\echo '=== [事前集計] 一覧 ==='
EXPLAIN (ANALYZE, BUFFERS)
WITH target AS (
  SELECT id, quantity FROM inventory
  WHERE company_id = 1 ORDER BY id LIMIT 50 OFFSET :offset
)
SELECT t.id, t.quantity, t.quantity + COALESCE(SUM(d.delta), 0) AS logical_quantity
FROM target t
LEFT JOIN scheduled_quantity_deltas d
  ON d.company_id = 1 AND d.inventory_id = t.id AND d.date <= :date
GROUP BY t.id, t.quantity ORDER BY t.id;

\echo '=== [直接集計] グラフ（日付ごとの合計。全日付の補完はアプリ側） ==='
EXPLAIN (ANALYZE, BUFFERS)
SELECT GREATEST(d, :from::date) AS day, SUM(q) FROM (
  SELECT scheduled_date AS d, quantity AS q FROM purchase_item
  WHERE company_id = 1 AND inventory_id = :inv AND status IN (0, 1) AND scheduled_date <= :to
  UNION ALL
  SELECT COALESCE(scheduled_date, DATE '1970-01-01'), -quantity FROM delivery_item
  WHERE company_id = 1 AND inventory_id = :inv AND status IN (0, 1)
    AND (scheduled_date <= :to OR scheduled_date IS NULL)
) x GROUP BY 1 ORDER BY 1;

\echo '=== [事前集計] グラフ ==='
EXPLAIN (ANALYZE, BUFFERS)
SELECT GREATEST(date, :from::date) AS day, SUM(delta)
FROM scheduled_quantity_deltas
WHERE company_id = 1 AND inventory_id = :inv AND date <= :to
GROUP BY 1 ORDER BY 1;
