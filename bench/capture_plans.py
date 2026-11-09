"""付録 A.1（50 在庫への付与）の SQL について、両 DB の実行計画を plans/ に保存する。

対象は高密度の 1 ページ目（在庫 id 1〜50）と最終ページ（199951〜200000）。
"""
import os

import psycopg
import pymysql

HERE = os.path.dirname(os.path.abspath(__file__))
DATE = "2027-12-31"
PAGES = {"page1": range(1, 51), "last": range(199951, 200001)}

A1 = """
SELECT t.id,
       t.quantity
       + COALESCE((SELECT SUM(pi.quantity) FROM purchase_item pi
                   WHERE pi.company_id = 1 AND pi.inventory_id = t.id
                     AND pi.status IN (0, 1) AND pi.scheduled_date <= '{d}'), 0)
       - COALESCE((SELECT SUM(di.quantity) FROM delivery_item di
                   WHERE di.company_id = 1 AND di.inventory_id = t.id
                     AND di.status IN (0, 1)
                     AND (di.scheduled_date <= '{d}' OR di.scheduled_date IS NULL)), 0)
FROM inventory t
WHERE t.company_id = 1 AND t.id IN ({ids})
ORDER BY t.id
"""

pg = psycopg.connect("dbname=bench user=postgres host=/var/run/postgresql port=5433", autocommit=True).cursor()
my = pymysql.connect(user="bench", password="bench", database="bench",
                     unix_socket="/var/run/mysqld/mysqld.sock", autocommit=True).cursor()

for label, ids in PAGES.items():
    sql = A1.format(d=DATE, ids=",".join(map(str, ids)))
    for _ in range(3):
        pg.execute(sql); pg.fetchall()
        my.execute(sql); my.fetchall()
    pg.execute("EXPLAIN (ANALYZE, BUFFERS) " + sql)
    with open(os.path.join(HERE, "plans", f"pg_a1_{label}.txt"), "w") as f:
        f.write("\n".join(r[0] for r in pg.fetchall()) + "\n")
    my.execute("EXPLAIN ANALYZE " + sql)
    with open(os.path.join(HERE, "plans", f"mysql_a1_{label}.txt"), "w") as f:
        f.write(my.fetchall()[0][0] + "\n")
print("saved")
