"""既存の一覧で決まった 50 在庫に予定フリー在庫数を付与するクエリだけを、直接集計と事前集計で比較する。

ページングは比較の外に出し（在庫 id を 50 件渡す）、両 DB・両方式で同じ Python クライアントから計測する。
status は計測データの都合で整数（0 = none、1 = before）。
"""
import time

import psycopg
import pymysql

DATE = "2027-12-31"
PAGES = {"1ページ目": range(1, 51), "2,001ページ目": range(100001, 100051), "最終ページ": range(199951, 200001)}

DIRECT = """
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

PRE = """
SELECT t.id,
       t.quantity + COALESCE((SELECT SUM(d.delta) FROM scheduled_quantity_deltas d
                              WHERE d.company_id = 1 AND d.inventory_id = t.id
                                AND d.date <= '{d}'), 0)
FROM inventory t
WHERE t.company_id = 1 AND t.id IN ({ids})
ORDER BY t.id
"""


def measure(cur, sql, n=200):
    for _ in range(3):
        cur.execute(sql)
        cur.fetchall()
    samples = []
    for _ in range(n):
        t0 = time.perf_counter()
        cur.execute(sql)
        rows = cur.fetchall()
        samples.append((time.perf_counter() - t0) * 1000)
    samples.sort()
    return samples[n // 2], samples[int(n * 0.95)], rows


conns = {
    "PostgreSQL": psycopg.connect("dbname=bench user=postgres host=/var/run/postgresql port=5433", autocommit=True),
    "MySQL": pymysql.connect(user="bench", password="bench", database="bench",
                             unix_socket="/var/run/mysqld/mysqld.sock", autocommit=True),
}
for db, conn in conns.items():
    cur = conn.cursor()
    for page, ids in PAGES.items():
        id_list = ",".join(map(str, ids))
        res = {}
        for name, q in (("直接集計", DIRECT), ("事前集計", PRE)):
            p50, p95, rows = measure(cur, q.format(d=DATE, ids=id_list))
            res[name] = [(r[0], float(r[1])) for r in rows]
            print(f"{db} {page} {name}: p50={p50:.1f}ms p95={p95:.1f}ms", flush=True)
        print(f"{db} {page} 結果一致: {res['直接集計'] == res['事前集計']}", flush=True)
