Import warehouses.csv or supplier_skus.json from the Data ingestion screen as Operations Analyst or Administrator.
They ADD new records to synthetic seed data. Repeated imports are rejected atomically, not silently overwritten.
JSON example: {"entity":"orders","records":[{"order_no":"ORD-NEW1","customer":"Sample","sku":"SENSOR-X","qty":8,"warehouse_id":1,"priority":"HIGH","sla_due":"2026-11-09T10:00:00+00:00","value":8000}]}
CSV filenames must exactly match one of: suppliers.csv, warehouses.csv, supplier_skus.csv,
inventory.csv, purchase_orders.csv, shipments.csv, orders.csv.
