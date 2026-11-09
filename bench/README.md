# 検証・計測の再現手順

本体の README の 4.3（受け入れテスト）、6 章、付録 B の数値を再現するためのスクリプト一式。

## 環境

- PostgreSQL 16（ポート 5433）／ MySQL 8.0（InnoDB）
- Python 3 と `psycopg`、`pymysql`
- 計測は 2 vCPU / 7GB メモリで行った。データはメモリに載った状態、1 クライアントで逐次実行。
- `pg_setup.sql` は `setseed(0.42)` で乱数を固定しているため、同じ PostgreSQL バージョンなら同じデータが生成される。

## 1. 受け入れテスト（README 4.3、4.1）

小さな固定データで、一覧の SQL（付録 A.1）とグラフの SQL（付録 A.2）を、業務上の期待値と比較する。完了処理の途中で数量を変更しようとするケースは、2 本の接続で実際にロックの待ちを発生させて確認する。status は課題どおり文字列。1 件でも不一致があれば終了コード 1 で終わる。

```bash
createdb -p 5433 acceptance
mysql -e "CREATE DATABASE acceptance; GRANT ALL ON acceptance.* TO 'bench'@'localhost';"
python3 acceptance_test.py
```

## 2. 計測用データの作成

```bash
# PostgreSQL にデータとインデックスを作成する（DB 名 bench）
createdb -p 5433 bench
psql -p 5433 -d bench -f pg_setup.sql

# MySQL に同じデータを投入する（PostgreSQL から CSV で移す。接続ユーザー: bench / bench）
./mysql_load.sh
```

- **status の型**：計測データでは、Rails の integer enum を想定して整数で保持した（PostgreSQL は smallint、MySQL は tinyint。0 = none、1 = before、2 = completed）。
- **明細数**：高密度の在庫には、入庫・出庫それぞれ 1,000 件（合計 2,000 件）を入れた。課題の「1 在庫最大 1,000 件」を入出庫の合算と解釈した場合の 2 倍にあたる。

## 3. 計測

```bash
# README 6 章・付録 B の方式比較：50 在庫への付与（直接集計 / 事前集計）を両 DB で計測し、結果の一致も確認する
python3 compare_aligned.py

# グラフの SQL の累積値が、一覧の SQL の値と一致することを計測データで確認する（不一致なら終了コード 1）
python3 graph_check.py

# 参考：ページングを含めて 1 文にした一覧（付録 B「SQL の形とページング」）
psql -p 5433 -d bench -v offset=199950 -f adopted_list_pg.sql               # 実行計画
psql -p 5433 -d bench -v offset=199950 -v inv=199951 -f pg_queries.sql      # UNION ALL 版・事前集計・グラフの実行計画
for n in adopted_p1 adopted_mid adopted_last pre_p1 pre_mid pre_last; do
  pgbench -p 5433 -n -c 1 -t 200 -f pgb_$n.sql --log --log-prefix=log_$n bench
done
python3 mysql_bench_adopted.py    # MySQL：遅延結合あり
python3 mysql_bench_compare.py    # MySQL：UNION ALL 版・遅延結合なし・事前集計
```

## 取得済みの実行計画（plans/）

```bash
python3 capture_plans.py   # 付録 A.1 の SQL の計画を両 DB で取得し、plans/ に保存する
```

| ファイル | 内容 |
|---|---|
| `pg_a1_page1.txt` / `pg_a1_last.txt` | 付録 A.1（採用 SQL）、PostgreSQL、高密度の 1 ページ目／最終ページ |
| `mysql_a1_page1.txt` / `mysql_a1_last.txt` | 同上、MySQL |
| `reference_paging/` | 参考：ページングを含めて 1 文にした一覧の計画（付録 B「SQL の形とページング」） |

確認する点：
- 明細は、両 DB ともインデックスだけで読んでいる（PostgreSQL は Index Only Scan で Heap Fetches 0、MySQL は Covering index lookup）。各在庫につき 1 回（loops=50）の範囲走査。
- 検索条件と判定条件の内訳は、DB・入出庫で異なる（本体 README 付録 A.3 の表）。PostgreSQL の入庫側だけ、予定日が Index Cond に現れる。
