-- 計測用スキーマ（MySQL 8.0, InnoDB）。データは PostgreSQL と同一のものを CSV で取り込む
DROP DATABASE IF EXISTS bench;
CREATE DATABASE bench;
USE bench;

CREATE TABLE inventory (
  id bigint PRIMARY KEY,
  company_id bigint NOT NULL,
  quantity decimal(15,3) NOT NULL
);
CREATE TABLE purchase_item (
  id bigint PRIMARY KEY,
  company_id bigint NOT NULL,
  purchase_id bigint NOT NULL,
  inventory_id bigint NOT NULL,
  status tinyint NOT NULL,
  scheduled_date date NULL,
  completed_date date NULL,
  quantity decimal(15,3) NOT NULL
);
CREATE TABLE delivery_item (
  id bigint PRIMARY KEY,
  company_id bigint NOT NULL,
  delivery_id bigint NOT NULL,
  inventory_id bigint NOT NULL,
  status tinyint NOT NULL,
  scheduled_date date NULL,
  completed_date date NULL,
  quantity decimal(15,3) NOT NULL
);
CREATE TABLE scheduled_quantity_deltas (
  company_id bigint NOT NULL,
  inventory_id bigint NOT NULL,
  date date NOT NULL,
  delta decimal(15,3) NOT NULL,
  PRIMARY KEY (company_id, inventory_id, date)
);

SET GLOBAL local_infile = 1;
