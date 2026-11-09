"""MySQL 8.0 で一覧クエリの実行計画と応答時間（p50/p95）を計測する。"""
import os
import time
import pymysql

HERE = os.path.dirname(os.path.abspath(__file__))

DATE = "2027-12-31"

Q_DIRECT_V1 = """
WITH target AS (
  SELECT id, quantity FROM inventory
  WHERE company_id = 1 ORDER BY id LIMIT 50 OFFSET {off}
),
pending AS (
  SELECT pi.inventory_id, pi.quantity AS qty
  FROM target t JOIN purchase_item pi ON pi.company_id = 1 AND pi.inventory_id = t.id
  WHERE pi.status IN (0, 1) AND pi.scheduled_date <= '{d}'
  UNION ALL
  SELECT di.inventory_id, -di.quantity
  FROM target t JOIN delivery_item di ON di.company_id = 1 AND di.inventory_id = t.id
  WHERE di.status IN (0, 1) AND (di.scheduled_date <= '{d}' OR di.scheduled_date IS NULL)
)
SELECT t.id, t.quantity, t.quantity + COALESCE(SUM(p.qty), 0) AS logical_quantity
FROM target t LEFT JOIN pending p ON p.inventory_id = t.id
GROUP BY t.id, t.quantity ORDER BY t.id
"""

Q_DIRECT_V2 = """
SELECT t.id, t.quantity,
       t.quantity
       + COALESCE((SELECT SUM(pi.quantity) FROM purchase_item pi
                   WHERE pi.company_id = 1 AND pi.inventory_id = t.id
                     AND pi.status IN (0, 1) AND pi.scheduled_date <= '{d}'), 0)
       - COALESCE((SELECT SUM(di.quantity) FROM delivery_item di
                   WHERE di.company_id = 1 AND di.inventory_id = t.id
                     AND di.status IN (0, 1)
                     AND (di.scheduled_date <= '{d}' OR di.scheduled_date IS NULL)), 0)
         AS logical_quantity
FROM (SELECT id, quantity FROM inventory
      WHERE company_id = 1 ORDER BY id LIMIT 50 OFFSET {off}) t
ORDER BY t.id
"""

Q_PRE = """
SELECT t.id, t.quantity,
       t.quantity + COALESCE((SELECT SUM(d.delta) FROM scheduled_quantity_deltas d
                              WHERE d.company_id = 1 AND d.inventory_id = t.id
                                AND d.date <= '{d}'), 0) AS logical_quantity
FROM (SELECT id, quantity FROM inventory
      WHERE company_id = 1 ORDER BY id LIMIT 50 OFFSET {off}) t
ORDER BY t.id
"""

conn = pymysql.connect(user="bench", password="bench", database="bench", unix_socket="/var/run/mysqld/mysqld.sock")
cur = conn.cursor()

results = {}
for name, q in [("direct_v1", Q_DIRECT_V1), ("direct_v2", Q_DIRECT_V2), ("pre", Q_PRE)]:
    for label, off in [("p1", 0), ("mid", 100000), ("last", 199950)]:
        sql = q.format(off=off, d=DATE)
        for _ in range(3):  # ウォームアップ
            cur.execute(sql); cur.fetchall()
        samples = []
        for _ in range(200):
            t0 = time.perf_counter()
            cur.execute(sql); rows = cur.fetchall()
            samples.append((time.perf_counter() - t0) * 1000)
        samples.sort()
        print(f"{name}_{label}: rows={len(rows)} p50={samples[100]:.1f}ms "
              f"p95={samples[190]:.1f}ms max={samples[-1]:.1f}ms", flush=True)
        if label == "last":
            cur.execute("EXPLAIN ANALYZE " + sql)
            with open(os.path.join(HERE, "plans", f"mysql_compare_{name}_last.txt"), "w") as f:
                f.write(cur.fetchall()[0][0])

# 3方式の結果が一致することを確認
for off in (0, 199950):
    outs = []
    for q in (Q_DIRECT_V1, Q_DIRECT_V2, Q_PRE):
        cur.execute(q.format(off=off, d=DATE))
        outs.append([(r[0], float(r[2])) for r in cur.fetchall()])
    print(f"offset={off} 結果一致: {outs[0] == outs[1] == outs[2]}")
