"""受け入れ条件（README 4.3）と完了処理の整合性（README 4.1）を、PostgreSQL と MySQL で検証する。

- status は課題どおり文字列（none / before / completed）で保持する。
- 一覧の SQL とグラフの SQL を、それぞれ業務上の期待値と比較する。
- 1 件でも不一致があれば終了コード 1 で終わる。
"""
import datetime as dt
import sys
import threading
import time

import psycopg
import pymysql

TODAY = dt.date(2026, 11, 16)
TOMORROW = TODAY + dt.timedelta(days=1)
DAY_AFTER = TODAY + dt.timedelta(days=2)
DAYS = [TODAY, TOMORROW, DAY_AFTER]
C = 1  # 対象アカウント

SCHEMA = [
    "DROP TABLE IF EXISTS purchase_item",
    "DROP TABLE IF EXISTS delivery_item",
    "DROP TABLE IF EXISTS inventory",
    "CREATE TABLE inventory (id bigint PRIMARY KEY, company_id bigint NOT NULL, quantity decimal(15,3) NOT NULL)",
    """CREATE TABLE purchase_item (id bigint PRIMARY KEY, company_id bigint NOT NULL, purchase_id bigint NOT NULL,
       inventory_id bigint NOT NULL, status varchar(16) NOT NULL, scheduled_date date NULL,
       completed_date date NULL, quantity decimal(15,3) NOT NULL)""",
    """CREATE TABLE delivery_item (id bigint PRIMARY KEY, company_id bigint NOT NULL, delivery_id bigint NOT NULL,
       inventory_id bigint NOT NULL, status varchar(16) NOT NULL, scheduled_date date NULL,
       completed_date date NULL, quantity decimal(15,3) NOT NULL)""",
    "CREATE INDEX idx_pi_pending ON purchase_item (company_id, inventory_id, status, scheduled_date, quantity)",
    "CREATE INDEX idx_di_pending ON delivery_item (company_id, inventory_id, status, scheduled_date, quantity)",
]

# 初期状態：現在庫 10、明日に入庫予定 5。
# 無関係なデータ（完了済みの明細、別アカウントの明細）も入れ、集計に混ざらないことを確かめる。
FIXTURE = [
    "INSERT INTO inventory VALUES (1, 1, 10), (2, 2, 100)",
    "INSERT INTO purchase_item VALUES (1, 1, 1, 1, 'before', '2026-11-17', NULL, 5)",
    "INSERT INTO purchase_item VALUES (2, 1, 2, 1, 'completed', '2026-11-10', '2026-11-10', 7)",
    "INSERT INTO purchase_item VALUES (3, 2, 3, 2, 'before', '2026-11-17', NULL, 50)",
    "INSERT INTO delivery_item VALUES (1, 2, 1, 2, 'none', NULL, NULL, 30)",
]

# README 付録 A.1 の一覧 SQL（既存の一覧で決めた在庫 id に予定フリー在庫数を付与する）
LIST_SQL = """
SELECT t.id,
       t.quantity
       + COALESCE((SELECT SUM(pi.quantity) FROM purchase_item pi
                   WHERE pi.company_id = %s AND pi.inventory_id = t.id
                     AND pi.status IN ('none', 'before')
                     AND pi.scheduled_date <= %s), 0)
       - COALESCE((SELECT SUM(di.quantity) FROM delivery_item di
                   WHERE di.company_id = %s AND di.inventory_id = t.id
                     AND di.status IN ('none', 'before')
                     AND (di.scheduled_date <= %s OR di.scheduled_date IS NULL)), 0)
FROM inventory t
WHERE t.company_id = %s AND t.id IN ({ids})
ORDER BY t.id
"""

# README 付録 A.2 のグラフ SQL
GRAPH_SQL = """
SELECT GREATEST(d, CAST(%s AS DATE)) AS day, SUM(q) AS amount
FROM (
  SELECT CAST(%s AS DATE) AS d, quantity AS q FROM inventory
  WHERE company_id = %s AND id = %s
  UNION ALL
  SELECT scheduled_date, quantity FROM purchase_item
  WHERE company_id = %s AND inventory_id = %s
    AND status IN ('none', 'before') AND scheduled_date <= %s
  UNION ALL
  SELECT COALESCE(scheduled_date, CAST(%s AS DATE)), -quantity FROM delivery_item
  WHERE company_id = %s AND inventory_id = %s
    AND status IN ('none', 'before') AND (scheduled_date <= %s OR scheduled_date IS NULL)
) x
GROUP BY 1 ORDER BY 1
"""


def list_values(conn, inventory_id):
    """一覧 API の値を、今日・明日・明後日それぞれの date で取得する。"""
    out = []
    with conn.cursor() as cur:
        for d in DAYS:
            cur.execute(LIST_SQL.format(ids="%s"), (C, d, C, d, C, inventory_id))
            out.append(float(cur.fetchone()[1]))
    conn.commit()
    return out


def graph_values(conn, inventory_id, frm=TODAY, to=DAY_AFTER):
    """グラフ API の値（全日付を埋めた累積値）を取得する。"""
    with conn.cursor() as cur:
        cur.execute(GRAPH_SQL, (frm, frm, C, inventory_id, C, inventory_id, to, frm, C, inventory_id, to))
        amounts = {row[0]: float(row[1]) for row in cur.fetchall()}
    conn.commit()
    values, acc, day = [], 0.0, frm
    while day <= to:
        acc += amounts.get(day, 0.0)
        values.append(acc)
        day += dt.timedelta(days=1)
    return values


def complete_item(conn, table, item_id):
    """README 4.1 の完了処理。明細をロックしてから、その行の数量と在庫 id で在庫を更新する。"""
    sign = 1 if table == "purchase_item" else -1
    with conn.cursor() as cur:
        cur.execute(f"SELECT inventory_id, quantity, status FROM {table} "
                    "WHERE company_id = %s AND id = %s FOR UPDATE", (C, item_id))
        row = cur.fetchone()
        if row is None or row[2] == "completed":
            conn.rollback()
            return False
        inventory_id, quantity, _ = row
        cur.execute(f"UPDATE {table} SET status = 'completed', completed_date = %s "
                    "WHERE company_id = %s AND id = %s", (TODAY, C, item_id))
        cur.execute("UPDATE inventory SET quantity = quantity + %s WHERE company_id = %s AND id = %s",
                    (sign * quantity, C, inventory_id))
    conn.commit()
    return True


def edit_quantity(conn, table, item_id, quantity):
    """README 4.1 の編集処理。完了済みの明細は数量を変更できない（更新件数 0 を返す）。"""
    with conn.cursor() as cur:
        cur.execute(f"UPDATE {table} SET quantity = %s "
                    "WHERE company_id = %s AND id = %s AND status <> 'completed'", (quantity, C, item_id))
        n = cur.rowcount
    conn.commit()
    return n


def execute(conn, *sqls):
    with conn.cursor() as cur:
        for s in sqls:
            cur.execute(s)
    conn.commit()


def inventory_quantity(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT quantity FROM inventory WHERE id = 1")
        q = float(cur.fetchone()[0])
    conn.commit()
    return q


# (名前, 操作, 期待値[今日, 明日, 明後日], 期待する現在庫)
SCENARIOS = [
    ("初期状態", lambda c, c2: None, [10, 15, 15], 10),
    ("入庫予定日を明後日に延期",
     lambda c, c2: execute(c, "UPDATE purchase_item SET scheduled_date = '2026-11-18' WHERE id = 1"),
     [10, 10, 15], 10),
    ("入庫予定の数量を 3 に変更",
     lambda c, c2: execute(c, "UPDATE purchase_item SET quantity = 3 WHERE id = 1"),
     [10, 13, 13], 10),
    ("入庫を完了", lambda c, c2: complete_item(c, "purchase_item", 1), [15, 15, 15], 15),
    ("入庫を 2 回完了しても二重加算しない",
     lambda c, c2: (complete_item(c, "purchase_item", 1), complete_item(c, "purchase_item", 1)),
     [15, 15, 15], 15),
    ("入庫予定日を NULL に変更",
     lambda c, c2: execute(c, "UPDATE purchase_item SET scheduled_date = NULL WHERE id = 1"),
     [10, 10, 10], 10),
    ("入庫明細を削除", lambda c, c2: execute(c, "DELETE FROM purchase_item WHERE id = 1"), [10, 10, 10], 10),
    ("日付未定・none の出庫 5 を登録",
     lambda c, c2: execute(c, "INSERT INTO delivery_item VALUES (10, 1, 10, 1, 'none', NULL, NULL, 5)"),
     [5, 10, 10], 10),
    ("日付未定の出庫 5 に明日の日付を設定",
     lambda c, c2: execute(c, "INSERT INTO delivery_item VALUES (10, 1, 10, 1, 'none', NULL, NULL, 5)",
                           "UPDATE delivery_item SET scheduled_date = '2026-11-17' WHERE id = 10"),
     [10, 10, 10], 10),
    ("明日の出庫 3 を登録して完了",
     lambda c, c2: (execute(c, "INSERT INTO delivery_item VALUES (11, 1, 11, 1, 'before', '2026-11-17', NULL, 3)"),
                    complete_item(c, "delivery_item", 11)),
     [7, 12, 12], 7),
    ("数量を 8 に変更してから完了（変更後の数量で加算する）",
     lambda c, c2: (edit_quantity(c2, "purchase_item", 1, 8), complete_item(c, "purchase_item", 1)),
     [18, 18, 18], 18),
]


def session_id(kind, conn):
    with conn.cursor() as cur:
        cur.execute("SELECT pg_backend_pid()" if kind == "PostgreSQL" else "SELECT CONNECTION_ID()")
        sid = cur.fetchone()[0]
    conn.commit()
    return sid


def waiting_for_lock(kind, monitor, sid):
    """DB のビューで、指定セッションが行ロックを待っているかを確認する。"""
    with monitor.cursor() as cur:
        if kind == "PostgreSQL":
            cur.execute("SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s", (sid,))
            row = cur.fetchone()
            return row is not None and row[0] == "Lock"
        cur.execute("SELECT trx_state FROM information_schema.innodb_trx WHERE trx_mysql_thread_id = %s", (sid,))
        row = cur.fetchone()
        return row is not None and row[0] == "LOCK WAIT"


def concurrent_edit_during_completion(kind, conn, conn2, monitor):
    """完了処理が明細をロックしている間に、別の接続が数量を 8 に変更しようとする。

    期待：変更はロック待ちになり、完了のコミット後は「完了済み」として拒否される（更新件数 0）。
    現在庫は完了時点の数量 5 だけ加算されて 15 になり、一覧とグラフは今日・明日・明後日とも 15。
    """
    result = {}
    sid = session_id(kind, conn2)
    with conn.cursor() as cur:
        cur.execute("SELECT inventory_id, quantity, status FROM purchase_item "
                    "WHERE company_id = %s AND id = 1 FOR UPDATE", (C,))
        inventory_id, quantity, _ = cur.fetchone()

        t = threading.Thread(target=lambda: result.update(n=edit_quantity(conn2, "purchase_item", 1, 8)))
        t.start()
        lock_wait = False
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not lock_wait:
            lock_wait = waiting_for_lock(kind, monitor, sid)
            time.sleep(0.05)

        cur.execute("UPDATE purchase_item SET status = 'completed', completed_date = %s "
                    "WHERE company_id = %s AND id = 1", (TODAY, C))
        cur.execute("UPDATE inventory SET quantity = quantity + %s WHERE company_id = %s AND id = %s",
                    (quantity, C, inventory_id))
    conn.commit()
    t.join(timeout=10)
    return lock_wait, result.get("n"), inventory_quantity(conn)


def connect(kind, autocommit=False):
    if kind == "PostgreSQL":
        return psycopg.connect("dbname=acceptance user=postgres host=/var/run/postgresql port=5433",
                               autocommit=autocommit)
    return pymysql.connect(user="bench", password="bench", database="acceptance",
                           unix_socket="/var/run/mysqld/mysqld.sock", autocommit=autocommit)


def reset(conn):
    execute(conn, *SCHEMA, *FIXTURE)


def main():
    failures = 0
    for kind in ("PostgreSQL", "MySQL"):
        conn, conn2, monitor = connect(kind), connect(kind), connect(kind, autocommit=True)
        for name, op, expected, expected_qty in SCENARIOS:
            reset(conn)
            op(conn, conn2)
            lv, gv, qty = list_values(conn, 1), graph_values(conn, 1), inventory_quantity(conn)
            ok = lv == expected and gv == expected and qty == expected_qty
            failures += not ok
            print(f"[{'OK' if ok else 'NG'}] {kind} {name}: 一覧={lv} グラフ={gv} 期待={expected} 現在庫={qty}")

        reset(conn)
        lock_wait, n, qty = concurrent_edit_during_completion(kind, conn, conn2, monitor)
        lv, gv = list_values(conn, 1), graph_values(conn, 1)
        ok = n == 0 and qty == 15 and lv == [15, 15, 15] and gv == [15, 15, 15]
        failures += not ok
        print(f"[{'OK' if ok else 'NG'}] {kind} 完了処理中の数量変更: 変更件数={n} 現在庫={qty} "
              f"一覧={lv} グラフ={gv}（DB 上のロック待ち観測={lock_wait}）")
        for c in (conn, conn2, monitor):
            c.close()

    print(f"\n失敗: {failures} 件")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
