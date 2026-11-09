"""採用案（README 3.2：遅延結合 + 相関サブクエリ）の一覧クエリを MySQL で計測する。"""
import time, pymysql
c = pymysql.connect(user="bench", password="bench", database="bench", unix_socket="/var/run/mysqld/mysqld.sock").cursor()
Q = """SELECT t.id, t.quantity
 + COALESCE((SELECT SUM(pi.quantity) FROM purchase_item pi WHERE pi.company_id = 1 AND pi.inventory_id = t.id AND pi.status IN (0, 1) AND pi.scheduled_date <= '2027-12-31'), 0)
 - COALESCE((SELECT SUM(di.quantity) FROM delivery_item di WHERE di.company_id = 1 AND di.inventory_id = t.id AND di.status IN (0, 1) AND (di.scheduled_date <= '2027-12-31' OR di.scheduled_date IS NULL)), 0)
FROM inventory t JOIN (SELECT id FROM inventory WHERE company_id = 1 ORDER BY id LIMIT 50 OFFSET {off}) x ON x.id = t.id ORDER BY t.id"""
for off in (0, 100000, 199950):
    sql = Q.format(off=off)
    for _ in range(3): c.execute(sql); c.fetchall()
    s = []
    for _ in range(200):
        t = time.perf_counter(); c.execute(sql); c.fetchall(); s.append((time.perf_counter()-t)*1000)
    s.sort(); print(f"遅延結合+直接集計 offset={off}: p50={s[100]:.1f}ms p95={s[190]:.1f}ms max={s[-1]:.1f}ms")
