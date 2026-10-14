import json
import tempfile
from pathlib import Path
import types
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from gold_candles.analysis import analyze
from gold_candles.cli import demo_bars, main
from gold_candles.data import Config, DataError, aggregate_m30, validate_bars, write_json
from gold_candles.features import chronological_masks, feature_frame, make_labels
from gold_candles.model import forecast, load_model, train
from gold_candles.mt5_reader import read_mt5
from gold_candles.patterns import atr14, flags, latest_patterns


class CandleTests(unittest.TestCase):
    def setUp(self):
        self.bars=demo_bars(240)
        self.end=self.bars.time_close_utc.iloc[-1]

    def test_forming_bar_excluded(self):
        raw=self.bars.tail(2).copy()
        as_of=raw.time_open_utc.iloc[-1]+pd.Timedelta(minutes=2)
        result=validate_bars(raw,5,as_of)
        self.assertEqual(len(result),1)

    def test_duplicate_bar_rejected(self):
        bad=pd.concat([self.bars,self.bars.tail(1)],ignore_index=True)
        with self.assertRaisesRegex(DataError,"DUPLICATE"):
            validate_bars(bad,5,self.end)

    def test_unsorted_bar_rejected(self):
        with self.assertRaisesRegex(DataError,"UNSORTED"):
            validate_bars(self.bars.iloc[::-1],5,self.end)

    def test_ohlc_geometry_rejected(self):
        bad=self.bars.copy();bad.loc[0,"high"]=1
        with self.assertRaisesRegex(DataError,"OHLC_GEOMETRY"):
            validate_bars(bad,5,self.end)

    def test_naive_time_rejected(self):
        bad=self.bars.copy();bad.time_open_utc=bad.time_open_utc.dt.tz_localize(None).astype(str)
        with self.assertRaisesRegex(DataError,"NAIVE"):
            validate_bars(bad,5,self.end)

    def test_epoch_is_utc_not_shifted(self):
        raw=self.bars.copy();raw["time"]=raw.time_open_utc.astype("int64")//10**9
        raw=raw.drop(columns="time_open_utc")
        result=validate_bars(raw,5,self.end)
        self.assertEqual(result.time_open_utc.iloc[0],self.bars.time_open_utc.iloc[0])

    def test_future_open_rejected(self):
        with self.assertRaisesRegex(DataError,"FUTURE_BAR"):
            validate_bars(self.bars,5,self.bars.time_open_utc.iloc[-2])

    def test_analysis_rejects_future_at_snapshot(self):
        with self.assertRaisesRegex(DataError,"NOT_CLOSED_AT_AS_OF"):
            analyze(self.bars,as_of=self.bars.time_close_utc.iloc[-2])

    def test_long_wick_rejection_survives_old_body_filter(self):
        bars=self.bars.copy()
        bars.loc[len(bars)-1,["open","high","low","close"]]=[4140,4140.30,4138.75,4140.25]
        result=latest_patterns(bars)
        self.assertIn("lower_wick_rejection",[p["name"] for p in result["patterns"]])
        self.assertLess(result["measurements"]["body_fraction"],.50)
        self.assertIsNone(result["probability"])

    def test_pattern_mirror_symmetry(self):
        mirrored=self.bars.copy()
        for col in ("open","close"):mirrored[col]=8280-self.bars[col]
        mirrored.high=8280-self.bars.low;mirrored.low=8280-self.bars.high
        a,b=flags(self.bars),flags(mirrored)
        for left,right in (("lower_wick_rejection","upper_wick_rejection"),
                           ("bullish_engulfing","bearish_engulfing"),
                           ("tweezer_bottom","tweezer_top"),
                           ("failed_breakdown","failed_breakout"),
                           ("bullish_displacement","bearish_displacement")):
            np.testing.assert_array_equal(a[left],b[right])

    def test_multibar_pattern_not_across_gap(self):
        bars=self.bars.copy()
        n=len(bars)
        bars.loc[n-2,["open","high","low","close"]]=[4142,4142.2,4140.8,4141]
        bars.loc[n-1,["open","high","low","close"]]=[4140.8,4142.5,4140.5,4142.3]
        bars.loc[n-1,"gap_before"]=True
        self.assertFalse(flags(bars).bullish_engulfing.iloc[-1])

    def test_wilder_seed(self):
        bars=self.bars.copy()
        bars[["open","close"]]=4140.;bars.high=4141.;bars.low=4139.
        result=atr14(bars)
        self.assertTrue(result.iloc[:13].isna().all())
        self.assertEqual(result.iloc[13],2.)
        self.assertEqual(result.iloc[-1],2.)

    def test_partial_m30_never_in_context(self):
        m5=self.bars.iloc[:237].copy()
        m30=aggregate_m30(m5)
        self.assertEqual(len(m30),39)
        self.assertLessEqual(m30.time_close_utc.max(),m5.time_close_utc.max())

    def test_missing_m5_invalidates_m30_bucket(self):
        m5=self.bars.drop(index=2).reset_index(drop=True)
        result=aggregate_m30(m5)
        self.assertEqual(len(result),39)
        self.assertNotIn(self.bars.time_open_utc.iloc[0],result.time_open_utc.tolist())

    def test_features_prefix_invariant(self):
        full,full_context=feature_frame(self.bars)
        prefix=self.bars.iloc[:215].copy()
        partial,partial_context=feature_frame(prefix)
        pd.testing.assert_frame_equal(full.iloc[:215],partial,check_flags=False)
        self.assertTrue((full_context.dropna()<=self.bars.time_close_utc[full_context.notna()]).all())

    def test_labels_not_across_market_gap(self):
        bars=self.bars.copy()
        bars.loc[120:,"time_open_utc"]+=pd.Timedelta(hours=1)
        bars.loc[120:,"time_close_utc"]+=pd.Timedelta(hours=1)
        labels,delta,end=make_labels(bars,3)
        self.assertTrue(labels.iloc[117:120].isna().all())
        self.assertTrue(labels.iloc[-3:].isna().all())

    def test_split_purges_label_horizon(self):
        times=self.bars.time_close_utc
        ends=times.shift(-6)
        fit,cal,hold,info=chronological_masks(times,ends)
        first_cal=pd.Timestamp(info["calibration_start_utc"])
        first_test=pd.Timestamp(info["holdout_start_utc"])
        self.assertTrue((ends[fit]<first_cal-pd.Timedelta(minutes=30)).all())
        self.assertTrue((ends[cal]<first_test-pd.Timedelta(minutes=30)).all())
        self.assertFalse((fit&cal).any());self.assertFalse((hold&cal).any())

    def test_no_model_is_not_fake_probability_or_signal(self):
        result=analyze(self.bars,as_of=self.end)
        self.assertEqual(result["forecast"]["status"],"NO_TRAINED_MODEL")
        self.assertIsNone(result["forecast"]["probabilities"])
        self.assertFalse(result["execution_lock"]["can_submit_order"])

    def test_live_stale_data_blocks_forecast(self):
        result=analyze(self.bars,as_of=self.end+pd.Timedelta(minutes=6),mode="LIVE")
        self.assertEqual(result["forecast"]["status"],"STALE_M5_DATA")

    def test_other_instrument_rejected(self):
        with self.assertRaisesRegex(DataError,"ONLY_XAUUSD"):
            Config(symbol="XAUT")

    def test_serialization_unknowns_become_null(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/"x.json"
            write_json(p,{"unknown":np.nan,"time":self.end})
            value=json.loads(p.read_text())
            self.assertIsNone(value["unknown"])

    def test_mt5_adapter_pos_one_and_utc_without_shift(self):
        m5=self.bars;m30=aggregate_m30(m5)
        def rates(frame):
            result=frame[["open","high","low","close","tick_volume"]].copy()
            result["time"]=frame.time_open_utc.astype("int64")//10**9
            return result.to_records(index=False)
        calls=[]
        fake=types.SimpleNamespace(TIMEFRAME_M5=5,TIMEFRAME_M30=30,
            initialize=lambda:True,shutdown=lambda:None,
            symbol_info=lambda s:types.SimpleNamespace(visible=True,currency_base="XAU",currency_profit="USD",trade_tick_size=.01,trade_contract_size=100),
            symbol_info_tick=lambda s:types.SimpleNamespace(time_msc=int(self.end.timestamp()*1000),bid=4140.,ask=4140.1))
        def copy(symbol,tf,pos,count):
            calls.append((tf,pos));return rates(m5 if tf==5 else m30)
        fake.copy_rates_from_pos=copy
        with patch.dict("sys.modules",{"MetaTrader5":fake}),patch("gold_candles.mt5_reader.utc",return_value=self.end+pd.Timedelta(seconds=1)):
            a,b,config,quote,now=read_mt5()
        self.assertEqual(calls,[(5,1),(30,1)])
        self.assertEqual(a.time_open_utc.iloc[0],self.bars.time_open_utc.iloc[0])
        self.assertTrue(quote["valid"])


class ResearchModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bars=demo_bars(2100,seed=17)
        cls.model,cls.report=train(cls.bars,trees=10,data_kind="SYNTHETIC_TEST")

    def test_three_horizons_native_export_and_probabilities(self):
        p=forecast(self.bars,model=self.model)
        self.assertEqual(set(p["probabilities"]),{"5","15","30"})
        for h in p["probabilities"].values():
            self.assertAlmostEqual(sum(h["probabilities"].values()),1.,places=12)
            q=h["close_price_quantiles"]
            self.assertLessEqual(q["q10"],q["q50"]);self.assertLessEqual(q["q50"],q["q90"])
            self.assertFalse(h["probability_quality_candidate"])
        self.assertFalse(p["execution_permission"])

    def test_model_future_relative_to_snapshot_abstains(self):
        early=self.bars.iloc[:1000].copy()
        p=forecast(early,model=self.model)
        self.assertEqual(p["status"],"MODEL_FROM_FUTURE_RELATIVE_TO_SNAPSHOT")
        self.assertIsNone(p["probabilities"])

    def test_contract_mismatch_rejected(self):
        with self.assertRaisesRegex(DataError,"CONTRACT_MISMATCH"):
            forecast(self.bars,config=Config(tick_size=.10),model=self.model)

    def test_m30_source_mismatch_rejected(self):
        with self.assertRaisesRegex(DataError,"SOURCE_MISMATCH"):
            forecast(self.bars,aggregate_m30(self.bars),model=self.model)

    def test_json_model_roundtrip_without_pickle(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"forecast.json";write_json(path,self.model)
            loaded=load_model(path)
            a=forecast(self.bars,model=self.model);b=forecast(self.bars,model=loaded)
            self.assertEqual(a,b)

    def test_calibration_labels_precede_holdout(self):
        for report in self.report["horizons"].values():
            self.assertLess(pd.Timestamp(report["calibration_labels_end_utc"]),pd.Timestamp(report["holdout_first_feature_utc"]))

    def test_model_does_not_unlock_strategy(self):
        result=analyze(self.bars,model=self.model,as_of=self.bars.time_close_utc.iloc[-1])
        self.assertEqual(result["execution_lock"]["state"],"BLOCKED")


if __name__=="__main__":
    unittest.main()
