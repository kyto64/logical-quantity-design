#!/usr/bin/env bash
# PostgreSQL で生成したダミーデータを CSV で書き出し、MySQL に投入してインデックスを作成する。
# 前提: pg_setup.sql を実行済みの PostgreSQL（ポート 5433、DB 名 bench）と、起動済みの MySQL 8.0。
set -euo pipefail
cd "$(dirname "$0")"
OUT="$(pwd)/csv"
export PGUSER="${PGUSER:-postgres}"
mkdir -p "$OUT"

# 1. PostgreSQL から CSV に書き出す（NULL は \N で出力し、MySQL の LOAD DATA で NULL として読む）
for t in inventory purchase_item delivery_item scheduled_quantity_deltas; do
  psql -p 5433 -d bench -c "\copy $t TO '$OUT/$t.csv' CSV NULL '\N'"
done

# 2. MySQL のスキーマを作成する
mysql -e "SET GLOBAL innodb_buffer_pool_size = 2147483648;"
mysql < mysql_setup.sql

# 3. CSV を投入する
for t in inventory purchase_item delivery_item scheduled_quantity_deltas; do
  mysql --local-infile=1 bench -e "LOAD DATA LOCAL INFILE '$OUT/$t.csv' INTO TABLE $t
    FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '\"'"
done

# 4. README 3.4 のインデックスを作成し、統計情報を更新する
mysql bench -e "
CREATE INDEX idx_inventory_company_id ON inventory (company_id, id);
CREATE INDEX idx_pi_pending ON purchase_item (company_id, inventory_id, status, scheduled_date, quantity);
CREATE INDEX idx_di_pending ON delivery_item (company_id, inventory_id, status, scheduled_date, quantity);
ANALYZE TABLE inventory, purchase_item, delivery_item, scheduled_quantity_deltas;"

# 5. 件数を確認する（期待値: 250000 / 1349500 / 1349500 / 704018）
mysql bench -e "SELECT
  (SELECT COUNT(*) FROM inventory) AS inventory,
  (SELECT COUNT(*) FROM purchase_item) AS purchase_item,
  (SELECT COUNT(*) FROM delivery_item) AS delivery_item,
  (SELECT COUNT(*) FROM scheduled_quantity_deltas) AS deltas;"
