-- CHARTS 1:1 (K3): plan levels of an SH signal stored with the signal (additive, new READY signals only): entry, SL, TP1..TP3 with
-- shares, net RR, BE rule, horizon. Older rows keep NULL - the chart shows "no levels in the signal record", nothing is reconstructed.
ALTER TABLE sh_signals ADD COLUMN levels TEXT;
