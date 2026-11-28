-- 1.46 arch (I0777): audit copy of the decision used for THIS order attempt (decision id + content hash, setup version, plan levels,
-- risk lots / entry / SL / targets, the values sent). decisions.record_json stays the first stored record of the decision id (its core
-- has no levels / volume, so a later decision with other SL / TP keeps the id); this column shows what was really sent. Additive:
-- older rows keep NULL, existing columns and rows are unchanged.
ALTER TABLE order_attempts ADD COLUMN decision_json TEXT;
