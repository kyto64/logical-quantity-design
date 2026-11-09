"""推移グラフの SQL（README 3.3）が両 DB で動き、一覧の SQL（3.2）と同じ値を返すことを確認する。"""
import subprocess, sys, pymysql
failures = 0
FROM, TO = "2026-11-16", "2027-02-14"
G = """SELECT GREATEST(d, DATE '{f}') AS day, SUM(q) AS amount FROM (
  SELECT DATE '{f}' AS d, quantity AS q FROM inventory WHERE company_id = 1 AND id = {i}
  UNION ALL
  SELECT scheduled_date, quantity FROM purchase_item
  WHERE company_id = 1 AND inventory_id = {i} AND status IN (0, 1) AND scheduled_date <= DATE '{t}'
  UNION ALL
  SELECT COALESCE(scheduled_date, DATE '{f}'), -quantity FROM delivery_item
  WHERE company_id = 1 AND inventory_id = {i} AND status IN (0, 1) AND (scheduled_date <= DATE '{t}' OR scheduled_date IS NULL)
) x GROUP BY 1 ORDER BY 1"""
L = """SELECT t.quantity
 + COALESCE((SELECT SUM(pi.quantity) FROM purchase_item pi WHERE pi.company_id = 1 AND pi.inventory_id = t.id AND pi.status IN (0, 1) AND pi.scheduled_date <= DATE '{d}'), 0)
 - COALESCE((SELECT SUM(di.quantity) FROM delivery_item di WHERE di.company_id = 1 AND di.inventory_id = t.id AND di.status IN (0, 1) AND (di.scheduled_date <= DATE '{d}' OR di.scheduled_date IS NULL)), 0)
FROM inventory t WHERE t.company_id = 1 AND t.id = {i}"""
def pg(sql):
    out = subprocess.run(["sudo","-u","postgres","psql","-p","5433","-d","bench","-At","-F","|","-c",sql],capture_output=True,text=True,check=True).stdout
    return [l.split("|") for l in out.strip().splitlines()]
my = pymysql.connect(user="bench", password="bench", database="bench", unix_socket="/var/run/mysqld/mysqld.sock").cursor()
def mysql(sql):
    my.execute(sql); return [[str(c) for c in r] for r in my.fetchall()]
import datetime
for inv in (1, 100000, 199951):
    for name, run in (("PG", pg), ("MySQL", mysql)):
        rows = run(G.format(f=FROM, t=TO, i=inv))
        acc, cum = 0.0, {}
        for day, amt in rows:
            acc += float(amt); cum[day] = acc
        days = sorted(cum)
        # チェック日: from, 中間の増減日, to
        checks = [FROM, days[len(days)//2], TO]
        ok = True
        for d in checks:
            g = cum[max(k for k in cum if k <= d)]
            l = float(run(L.format(d=d, i=inv))[0][0])
            ok &= abs(g - l) < 1e-9
        failures += not ok
        print(f"[{'OK' if ok else 'NG'}] {name} inventory={inv}: グラフ行数={len(rows)} 一覧と一致={ok}")

print(f"失敗: {failures} 件")
sys.exit(1 if failures else 0)
