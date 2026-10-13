"""固定標本・配札単位の評価。途中経過から採用判定しない。"""
from math import ceil,log,sqrt
from statistics import NormalDist
import numpy as np
from pydantic import BaseModel,ConfigDict,Field


class PlanningInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    observed_deals:int=Field(strict=True,ge=0,le=100000)
    mean_difference:float|None=Field(default=None,ge=-4,le=4,allow_inf_nan=False)
    sd_difference:float|None=Field(default=None,ge=0,le=8,allow_inf_nan=False)
    minimum_effect:float=Field(default=.25,ge=.001,le=4,allow_inf_nan=False)
    alpha:float=Field(default=.05,ge=.000001,le=.2,allow_inf_nan=False)
    power:float=Field(default=.8,gt=.5,lt=1,allow_inf_nan=False)
    max_deals:int=Field(default=1000,strict=True,ge=10,le=100000)
    comparisons:int=Field(default=1,strict=True,ge=1,le=100)
    seconds_per_deal:float|None=Field(default=None,gt=0,le=100000,allow_inf_nan=False)


def plan_samples(request, *, bound=4):
    r=request;alpha=r.alpha/r.comparisons
    base={'observed_deals':r.observed_deals,'minimum_effect':r.minimum_effect,'adjusted_alpha':alpha,
          'assumptions':'独立・代表的な配札差、将来も同じ分散。両側正規近似による固定標本設計。観測平均を真の効果に使わない。',
          'uncertainty':'分散推定と計算時間は不安定。概算は検出力の保証や逐次停止規則ではない。',
          'estimated_total':None,'estimated_additional':None,'estimated_seconds':None,'feasible':None,
          'conservative_total':None,'conservative_additional':None,'conservative_seconds':None}
    if r.observed_deals<10 or r.sd_difference is None or r.sd_difference==0:
        additional=max(0,10-r.observed_deals) if r.observed_deals<10 else 10
        return {**base,'status':'pilot_required','feasible':r.observed_deals+additional<=r.max_deals,'reason':'予備評価が必要：10配札未満、分散不明または分散0。精密な必要数を出しません。',
                'pilot_additional':additional,'pilot_seconds':additional*r.seconds_per_deal if r.seconds_per_deal else None}
    z=NormalDist()
    total=max(10,ceil(((z.inv_cdf(1-alpha/2)+z.inv_cdf(r.power))*r.sd_difference/r.minimum_effect)**2))
    additional=max(0,total-r.observed_deals)
    # 差は[-4,4]。Hoeffding区間を使う正式な固定標本判定に対応する保守的設計。
    conservative=ceil(2*bound**2*(sqrt(log(2/alpha))+sqrt(log(1/(1-r.power))))**2/r.minimum_effect**2)
    return {**base,'status':'approximate','reason':'観測平均ではなく事前指定した最小改善幅を使用。',
            'estimated_total':total,'estimated_additional':additional,'estimated_seconds':additional*r.seconds_per_deal if r.seconds_per_deal else None,
            'feasible':total<=r.max_deals,'conservative_total':conservative,'conservative_additional':max(0,conservative-r.observed_deals),
            'conservative_seconds':max(0,conservative-r.observed_deals)*r.seconds_per_deal if r.seconds_per_deal else None,
            'conservative_feasible':conservative<=r.max_deals}


def fixed_evidence(samples, *, alpha=.05, comparisons=1, completed=False, confirmatory=False, bound=4):
    values=list(samples);n=len(values)
    mean=float(np.mean(values)) if n else None
    sd=float(np.std(values,ddof=1)) if n>=2 else None
    result={'independent_deals':n,'mean':mean,'sd':sd,'adjusted_alpha':alpha/comparisons,'interval':None,
            'decision':'hold','method':'固定標本Hoeffding境界＋Bonferroni。逐次判定ではない。'}
    if not completed:return {**result,'reason':'未完了。途中経過から統計的判定をしません。'}
    if n<10:return {**result,'reason':'独立配札10件未満。区間・改善判定を提供しません。'}
    radius=2*bound*sqrt(log(2*comparisons/alpha)/(2*n))
    interval=[max(-bound,mean-radius),min(bound,mean+radius)]
    if not confirmatory:return {**result,'interval':interval,'reason':'開発用または事後分析。確証的改善判定はしません。'}
    return {**result,'interval':interval,'decision':'positive' if interval[0]>0 else 'negative' if interval[1]<0 else 'hold',
            'reason':'事前固定した標本数・比較集合の完了後だけ判定。分散0でも区間を縮め切りません。'}


def factorial_contrasts(cells):
    """配札ごとの2×2：00,10,01,11。順序を固定して差の差を計算。"""
    if len(cells)!=4 or len({len(c) for c in cells})!=1:raise ValueError('4条件の対応標本数が必要です')
    a,b,c,d=[np.asarray(v,dtype=float) for v in cells]
    return {'factor_a':(b-a).tolist(),'factor_b':(c-a).tolist(),'combined':(d-a).tolist(),'interaction':(d-b-c+a).tolist()}
