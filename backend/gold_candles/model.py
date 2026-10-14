from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import json
import platform

import numpy as np
import pandas as pd

from .data import Config, DataError, clean_json, utc, write_json
from .features import chronological_masks, feature_frame, make_labels
from .patterns import measurements


CLASS_NAMES = ("DOWN", "FLAT", "UP")
SCHEMA = "masterquo-candle-forecast-json-2.0"


def softmax(scores):
    scores = np.asarray(scores,dtype=float)
    values = np.exp(scores-scores.max(axis=1,keepdims=True))
    return values/values.sum(axis=1,keepdims=True)


def export_logistic(estimator):
    if list(estimator.classes_) != [0,1,2]:
        raise DataError("ALL_THREE_CLASSES_REQUIRED")
    return dict(coef=estimator.coef_.tolist(),intercept=estimator.intercept_.tolist())


def logistic_probability(x,model):
    coef = np.asarray(model["coef"],dtype=float)
    intercept = np.asarray(model["intercept"],dtype=float)
    if coef.shape != (3,x.shape[1]) or intercept.shape != (3,):
        raise DataError("MODEL_COEFFICIENT_SHAPE_MISMATCH")
    if not np.isfinite(coef).all() or not np.isfinite(intercept).all():
        raise DataError("NONFINITE_MODEL_COEFFICIENTS")
    return softmax(x@coef.T+intercept)


def export_quantile(estimator):
    trees=[]
    for stage in estimator.estimators_:
        t=stage[0].tree_
        trees.append(dict(left=t.children_left.tolist(),right=t.children_right.tolist(),
                          feature=t.feature.tolist(),threshold=t.threshold.tolist(),
                          value=t.value[:,0,0].tolist()))
    return dict(initial=float(estimator.init_.constant_[0,0]),
                learning_rate=float(estimator.learning_rate),trees=trees)


def quantile_prediction(x,model):
    # sklearn tree prediction casts its inputs to float32; mirror that contract.
    rows=np.asarray(x,dtype=np.float32)
    prediction=np.full(len(rows),float(model["initial"]),dtype=float)
    for tree in model["trees"]:
        arrays={key:np.asarray(tree[key]) for key in ("left","right","feature","threshold","value")}
        n=len(arrays["left"])
        if n==0 or any(len(a)!=n for a in arrays.values()):
            raise DataError("MALFORMED_TREE")
        values=[]
        for row in rows:
            node=0
            for _ in range(n+1):
                if node<0 or node>=n:
                    raise DataError("MALFORMED_TREE_INDEX")
                left=int(arrays["left"][node])
                if left == -1:
                    if int(arrays["right"][node]) != -1:
                        raise DataError("MALFORMED_TREE_LEAF")
                    values.append(float(arrays["value"][node]))
                    break
                feature=int(arrays["feature"][node])
                if feature<0 or feature>=len(row):
                    raise DataError("MALFORMED_TREE_FEATURE")
                node=left if row[feature]<=arrays["threshold"][node] else int(arrays["right"][node])
            else:
                raise DataError("CYCLIC_TREE")
        prediction += float(model["learning_rate"])*np.asarray(values)
    if not np.isfinite(prediction).all():
        raise DataError("NONFINITE_QUANTILE_PREDICTION")
    return prediction


def calibration_error(y,prob,bins=8):
    """Per-class equal-width ECE; not an independent confidence guarantee."""
    errors={}
    for cls,name in enumerate(CLASS_NAMES):
        total=0.0
        for lower in np.linspace(0,1,bins+1)[:-1]:
            upper=lower+1/bins
            mask=(prob[:,cls]>=lower)&(prob[:,cls]<(upper if upper<1 else 1.000001))
            if mask.any():
                total += mask.mean()*abs((y[mask]==cls).mean()-prob[mask,cls].mean())
        errors[name]=float(total)
    return errors


def metrics(y,prob):
    observed=np.eye(3)[y]
    predicted=prob.argmax(axis=1)
    recall=[float((predicted[y==cls]==cls).mean()) if (y==cls).any() else None for cls in range(3)]
    return dict(samples=len(y),accuracy=float((predicted==y).mean()),
                balanced_accuracy=float(np.mean([r for r in recall if r is not None])),
                brier_multiclass_sum=float(np.mean(np.sum((prob-observed)**2,axis=1))),
                log_loss=float(-np.log(np.clip(prob[np.arange(len(y)),y],1e-12,1)).mean()),
                per_class_recall=dict(zip(CLASS_NAMES,recall)),
                per_class_ece=calibration_error(y,prob),
                class_counts={name:int((y==cls).sum()) for cls,name in enumerate(CLASS_NAMES)})


def train(m5,m30=None,config=Config(),trees=80,data_kind="REAL_USER_DATA"):
    from sklearn import __version__ as sklearn_version
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import GradientBoostingRegressor

    if data_kind not in ("REAL_USER_DATA","SYNTHETIC_TEST"):
        raise DataError("UNKNOWN_DATA_KIND")
    if trees<10 or trees>200:
        raise DataError("TREES_MUST_BE_10_TO_200")
    x,ctx_times=feature_frame(m5,m30,config)
    usable=x.notna().all(axis=1)
    if usable.sum()<1500:
        raise DataError("TRAINING_REQUIRES_AT_LEAST_1500_COMPLETE_FEATURE_ROWS")
    artifact=dict(schema=SCHEMA,config=asdict(config),contract_hash=config.contract_hash(),
                  feature_names=list(x.columns),context_source=x.attrs["context_source"],
                  created_at_utc=utc().isoformat(),data_kind=data_kind,
                  validation_status="RESEARCH_ONLY_NOT_STRATEGY_VALIDATION",
                  versions=dict(python=platform.python_version(),numpy=np.__version__,
                                pandas=pd.__version__,scikit_learn=sklearn_version),models={})
    summary=dict(data_kind=data_kind,status="RESEARCH_ONLY",symbol=config.symbol,
                 feature_rows=int(usable.sum()),horizons={},
                 meaning="Future close direction and distribution; not TP-before-SL probabilities or trading P&L.")
    for horizon in config.horizons:
        labels,delta,label_end=make_labels(m5,horizon,config)
        valid=usable&labels.notna()&delta.notna()&label_end.notna()
        indices=np.flatnonzero(valid.to_numpy())
        xx=x.loc[valid].reset_index(drop=True)
        yy=labels.loc[valid].astype(int).reset_index(drop=True)
        dd=delta.loc[valid].reset_index(drop=True)
        times=m5.time_close_utc.loc[valid].reset_index(drop=True)
        ends=label_end.loc[valid].reset_index(drop=True)
        fit,cal,hold,split=chronological_masks(times,ends)
        for name,mask,minimum in (("fit",fit,600),("calibration",cal,200),("holdout",hold,250)):
            if mask.sum()<minimum:
                raise DataError(f"INSUFFICIENT_{name.upper()}_ROWS_H{horizon}")
            counts=yy[mask].value_counts()
            if not all(counts.get(cls,0)>=10 for cls in range(3)):
                raise DataError(f"INSUFFICIENT_CLASS_COVERAGE_{name}_H{horizon}")
        scaler=StandardScaler().fit(xx[fit])
        zfit=scaler.transform(xx[fit])
        classifier=LogisticRegression(C=.5,max_iter=2000,class_weight="balanced",random_state=17).fit(zfit,yy[fit])
        raw_cal=classifier.predict_proba(scaler.transform(xx[cal]))
        # Chronologically separate multinomial probability calibration.
        calibrator=LogisticRegression(C=.1,max_iter=2000,random_state=17).fit(np.log(np.clip(raw_cal,1e-12,1)),yy[cal])
        xhold=xx[hold].to_numpy()
        raw_hold=classifier.predict_proba(scaler.transform(xx[hold]))
        prob=calibrator.predict_proba(np.log(np.clip(raw_hold,1e-12,1)))
        baseline_prior=np.bincount(yy[fit],minlength=3)/fit.sum()
        baseline=np.repeat(baseline_prior[None,:],hold.sum(),axis=0)
        report=dict(split=split,fit_samples=int(fit.sum()),calibration_samples=int(cal.sum()),
                    holdout_samples=int(hold.sum()),fit_labels_end_utc=ends[fit].max().isoformat(),
                    calibration_labels_end_utc=ends[cal].max().isoformat(),
                    holdout_first_feature_utc=times[hold].min().isoformat(),
                    holdout_last_feature_utc=times[hold].max().isoformat(),
                    holdout_days=int(times[hold].dt.floor("D").nunique()),
                    calibrated=metrics(yy[hold].to_numpy(),prob),
                    baseline=metrics(yy[hold].to_numpy(),baseline))
        native=dict(mean=scaler.mean_.tolist(),scale=scaler.scale_.tolist(),
                    classifier=export_logistic(classifier),calibrator=export_logistic(calibrator),
                    quantiles={},knowledge_cutoff_utc=ends[cal].max().isoformat())
        quantiles=[]
        for quantile in (.1,.5,.9):
            qmodel=GradientBoostingRegressor(loss="quantile",alpha=quantile,n_estimators=trees,
                                             max_depth=2,learning_rate=.05,random_state=17).fit(xx[fit],dd[fit])
            exported=export_quantile(qmodel)
            native["quantiles"][str(quantile)]=exported
            prediction=quantile_prediction(xhold,exported)
            if not np.allclose(prediction,qmodel.predict(xx[hold]),rtol=1e-10,atol=1e-10):
                raise DataError("PORTABLE_QUANTILE_EXPORT_VERIFICATION_FAILED")
            quantiles.append(prediction)
        ordered=np.sort(np.column_stack(quantiles),axis=1)
        truth=dd[hold].to_numpy()
        report["quantiles"]=dict(central_80pct_empirical_coverage=float(((truth>=ordered[:,0])&(truth<=ordered[:,2])).mean()),
                                  median_mae_atr=float(np.abs(truth-ordered[:,1]).mean()),
                                  quantile_crossing_fraction_before_rearrangement=float((np.diff(np.column_stack(quantiles),axis=1)<0).any(axis=1).mean()))
        native_prob=logistic_probability(np.log(np.clip(logistic_probability((xhold-scaler.mean_)/scaler.scale_,native["classifier"]),1e-12,1)),native["calibrator"])
        if not np.allclose(native_prob,prob,rtol=1e-10,atol=1e-10):
            raise DataError("PORTABLE_CLASSIFIER_EXPORT_VERIFICATION_FAILED")
        report["probability_quality_candidate"] = bool(
            report["holdout_days"]>=30 and
            report["calibrated"]["brier_multiclass_sum"]<report["baseline"]["brier_multiclass_sum"] and
            report["calibrated"]["log_loss"]<report["baseline"]["log_loss"] and
            max(report["calibrated"]["per_class_ece"].values())<=.10 and data_kind=="REAL_USER_DATA")
        native["report"]=report
        artifact["models"][str(horizon)]=native
        summary["horizons"][str(horizon*5)]=report
    return clean_json(artifact),clean_json(summary)


def load_model(path):
    source=Path(path)
    if source.stat().st_size>50*1024*1024:
        raise DataError("MODEL_JSON_TOO_LARGE")
    model=json.loads(source.read_text(encoding="utf-8"))
    if model.get("schema")!=SCHEMA:
        raise DataError("MODEL_SCHEMA_MISMATCH")
    # JSON contains coefficients and numeric trees, never executable pickle.
    return model


def forecast(m5,m30=None,config=Config(),model=None):
    if model is None:
        return dict(status="NO_TRAINED_MODEL",probabilities=None,
                    horizons_minutes=[5,15,30],execution_permission=False)
    if model.get("schema")!=SCHEMA or model.get("contract_hash")!=config.contract_hash():
        raise DataError("MODEL_CONFIG_OR_SYMBOL_CONTRACT_MISMATCH")
    x,context_time=feature_frame(m5,m30,config)
    if model["feature_names"]!=list(x.columns) or model["context_source"]!=x.attrs["context_source"]:
        raise DataError("MODEL_FEATURE_OR_M30_SOURCE_MISMATCH")
    row=x.iloc[-1].to_numpy(dtype=float)[None,:]
    if not np.isfinite(row).all():
        return dict(status="FEATURE_WARMUP_OR_STALE_M30",probabilities=None,execution_permission=False)
    as_of=m5.time_close_utc.iloc[-1]
    for component in model["models"].values():
        if utc(component["knowledge_cutoff_utc"])>=as_of:
            return dict(status="MODEL_FROM_FUTURE_RELATIVE_TO_SNAPSHOT",probabilities=None,execution_permission=False)
    atr=float(measurements(m5).atr.iloc[-1])
    close=float(m5.close.iloc[-1])
    results={}
    for horizon in config.horizons:
        component=model["models"][str(horizon)]
        scale=np.asarray(component["scale"],dtype=float)
        if scale.shape!=(row.shape[1],) or (scale<=0).any() or not np.isfinite(scale).all():
            raise DataError("MODEL_SCALER_INVALID")
        z=(row-np.asarray(component["mean"],dtype=float))/scale
        raw=logistic_probability(z,component["classifier"])
        p=logistic_probability(np.log(np.clip(raw,1e-12,1)),component["calibrator"])[0]
        dq=np.sort([float(quantile_prediction(row,component["quantiles"][str(q)])[0])*atr for q in (.1,.5,.9)])
        results[str(horizon*5)]=dict(horizon_minutes=horizon*5,
            target_time_utc=(as_of+pd.Timedelta(minutes=horizon*5)).isoformat(),
            probabilities=dict(zip(CLASS_NAMES,map(float,p))),
            neutral_band_price=config.neutral_atr*atr,
            delta_price_quantiles=dict(zip(("q10","q50","q90"),map(float,dq))),
            close_price_quantiles=dict(zip(("q10","q50","q90"),map(float,close+dq))),
            probability_quality_candidate=component["report"]["probability_quality_candidate"],
            quantile_note="Rearranged conditional estimates; coverage is not guaranteed.")
    return dict(status="SHADOW_RESEARCH_FORECAST",data_kind=model["data_kind"],
                probabilities=results,feature_time_utc=as_of.isoformat(),
                m30_context_closed_at=context_time.iloc[-1].isoformat(),
                price_basis="INPUT_OHLC_CLOSE_NOT_EXECUTABLE_ASK_OR_BID_PNL",
                continuity_assumption="Requires continuous M5 trading during the horizon; broker session calendar is not integrated.",
                execution_permission=False)

