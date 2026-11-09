
SELECT t.id, t.quantity,
       t.quantity
       + COALESCE((SELECT SUM(pi.quantity) FROM purchase_item pi
                   WHERE pi.company_id = 1 AND pi.inventory_id = t.id
                     AND pi.status IN (0, 1) AND pi.scheduled_date <= '2027-12-31'), 0)
       - COALESCE((SELECT SUM(di.quantity) FROM delivery_item di
                   WHERE di.company_id = 1 AND di.inventory_id = t.id
                     AND di.status IN (0, 1)
                     AND (di.scheduled_date <= '2027-12-31' OR di.scheduled_date IS NULL)), 0)
         AS logical_quantity
FROM inventory t
JOIN (SELECT id FROM inventory WHERE company_id = 1
      ORDER BY id LIMIT 50 OFFSET 199950) page ON page.id = t.id
ORDER BY t.id;
