-- 1.4: licensing - time of the online operation authorization that preceded order_send (broker time comes later)
ALTER TABLE order_attempts ADD COLUMN authorized_at TEXT;
