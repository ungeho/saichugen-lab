"""未検証の戦術仮説。観測だけを受け取り、規則・勝敗を変更しない。"""
from dataclasses import asdict, dataclass
from math import isfinite
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..game.cards import deck


@dataclass(frozen=True)
class TheoryDefinition:
    id: str
    name: str
    description: str
    rationale: str
    information: tuple[str,...]
    applicability: str
    parameters: dict
    relationship: str
    limitations: tuple[str,...]
    evaluation: str
    version: str = "1"
    status: str = "未検証の仮説"
    scale: str = "−1〜+1の代理評価。期待終局報酬・勝率ではない"


_registry: dict[str,tuple[TheoryDefinition,Callable]] = {}


def register_theory(definition, evaluator):
    if not definition.id or definition.id in _registry or not callable(evaluator):
        raise ValueError("仮説IDは一意で評価器が必要です")
    _registry[definition.id]=(definition,evaluator)


def theory_catalog():
    return [asdict(d) for d,f in _registry.values()]


class TheorySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    version: str = "1"
    enabled: bool = Field(default=True,strict=True)
    weight: float = Field(default=1.0,strict=True,ge=-2,le=2,allow_inf_nan=False)
    params: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid(self):
        if self.id not in _registry or self.version!=_registry[self.id][0].version:
            raise ValueError("未知の仮説IDまたは版です")
        schema=_registry[self.id][0].parameters
        if set(self.params)-set(schema):
            raise ValueError("未知の仮説パラメータです")
        for name,value in self.params.items():
            spec=schema[name]
            if 'choices' in spec:
                if value not in spec['choices'] or type(value) is not type(spec['default']):
                    raise ValueError(f"{name}の選択値が不正です")
            elif type(value) not in (int,float) or not isfinite(value) or not spec['min']<=value<=spec['max']:
                raise ValueError(f"{name}の数値が範囲外です")
        self.params={**{k:v['default'] for k,v in schema.items()},**self.params}
        for key,value in self.params.items():
            if 'choices' not in schema[key]:self.params[key]=float(value)
        return self

    @property
    def values(self):
        return {**{k:v['default'] for k,v in _registry[self.id][0].parameters.items()},**self.params}


class TheoryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    theories: list[TheorySpec] = Field(default_factory=list,max_length=16)
    tie_break: Literal['seeded_random','card_order'] = 'seeded_random'

    @model_validator(mode="after")
    def unique(self):
        if len({s.id for s in self.theories})!=len(self.theories):
            raise ValueError("同じ仮説IDは重複指定できません")
        self.theories=sorted(self.theories,key=lambda s:s.id)
        return self


def _pool(obs,public=True):
    return obs.unseen_cards if public else tuple(c for c in deck() if c not in obs.hand)


def _probability(card,pool):
    n=len(pool)
    if n<2:return 0.0
    low=sum(c<card for c in pool);high=sum(c>card for c in pool)
    return 2*low*high/(n*(n-1))


def _reserve(obs,card,params,middle=False):
    if obs.turn>=14 or len(obs.hand)<=1:
        return 0.0,False,"最後の選択では温存札を再使用できないため不適用",{}
    remaining=[c for c in obs.hand if c!=card]
    test=(lambda c:abs(c.rank-params['center'])<=params['width']) if middle else (lambda c:c.rank>=params['threshold'])
    ratio=sum(test(c) for c in remaining)/len(remaining)
    horizon=(14-obs.turn)/14
    value=ratio*horizon*(1 if params['mode']=='preserve' else -1)
    return value,True,"残す対象札の割合×残り選択機会。未使用の2枚に残るだけなら利益とは限りません。",{'remaining_ratio':ratio,'horizon':horizon}


def _round_value(obs,card,p):
    own=obs.round_scores[obs.player];others=[s for i,s in enumerate(obs.round_scores) if i!=obs.player]
    target=sum(others)/2
    distance=(1-p)*abs(own-target)+p*abs(own+card.rank-target)
    return -min(1,distance/39)


def _cumulative_value(obs,card,p):
    # 相手点固定・このラウンドの終わりと仮定した代理値。実際の得点処理ではない。
    own=obs.round_scores[obs.player];others=[s for i,s in enumerate(obs.round_scores) if i!=obs.player]
    totals=obs.game_scores;target=sum(s for i,s in enumerate(totals) if i!=obs.player)/2
    def distance(score):
        award=score if min(others)<=score<=max(others) else 0
        return abs(totals[obs.player]+award-target)
    horizon=max(1,5-obs.turn//3)
    return -min(1,((1-p)*distance(own)+p*distance(own+card.rank))/(39*horizon))


def _round(obs,card,params):
    p=_probability(card,_pool(obs))
    r,g=_round_value(obs,card,p),_cumulative_value(obs,card,p)
    value=r if params['mode']=='round' else g if params['mode']=='cumulative' else (r+g)/2
    return value,True,"相手得点を固定し、中間の目標からの予想距離を小さくする代理評価。",{'round_proxy':r,'cumulative_proxy':g,'turn_probability':p}


def _cumulative(obs,card,params):
    p=_probability(card,_pool(obs));value=_cumulative_value(obs,card,p)
    return value,True,"現在の累計中間目標との距離を残りラウンドの最大39点で割る。最終勝率の推定ではありません。",{'turn_probability':p,'remaining_rounds':5-obs.turn//3}


def _memory(obs,card,params):
    pool=_pool(obs,params['public']);p=_probability(card,pool)
    return p,True,"未知札から2枚を一様に出すモデル。"+("公開済み札を除外。" if params['public'] else "公開履歴を使わず現在の手札以外を仮想分布に含めるため、既出札も含み得ます。"),{'pool_size':len(pool),'turn_probability':p}


def _opponents(obs,card,params):
    pool=_pool(obs);n=len(pool)
    if n<3:return 0.0,False,"未知札不足",{}
    ordered=sorted(pool);target=sorted(obs.round_scores)[1]
    opponents=[i for i in range(3) if i!=obs.player]
    desires=[1 if obs.round_scores[i]<=target else -1 for i in opponents]
    middle=[2*i*(n-1-i)/((n-1)*(n-2)) for i in range(n)]
    weights=[[1+params['strength']*(p if desire>0 else 1-p) for p in middle] for desire in desires]
    w1,w2=weights;s1,s2=sum(w1),sum(w2)
    low=sum(w for c,w in zip(ordered,w2) if c<card);high=s2-low
    probability=sum(w1[i]/s1*(high if c<card else low)/(s2-w2[i]) for i,c in enumerate(ordered))
    desire=1 if obs.round_scores[obs.player]<=target else -1
    return desire*probability,True,"相手はラウンド中位以下なら獲得、上なら回避を狙うと仮定。意図の観測ではありません。",{'opponent_1_desire':desires[0],'opponent_2_desire':desires[1],'turn_probability':probability,'own_desire':desire}


def evaluate_theory(observation,legal_action,config):
    spec=config if isinstance(config,TheorySpec) else TheorySpec.model_validate(config)
    if legal_action not in observation.legal_actions:
        raise ValueError("合法手だけを評価できます")
    if not spec.enabled or spec.weight==0:
        return {'id':spec.id,'version':spec.version,'value':0.0,'applicable':False,'explanation':'無効または重み0','components':{}}
    value,applicable,reason,components=_registry[spec.id][1](observation,legal_action,spec.values)
    if not isfinite(value) or not -1.0000001<=value<=1.0000001:
        raise ValueError("仮説評価は−1〜+1の有限値が必要です")
    return {'id':spec.id,'version':spec.version,'value':max(-1,min(1,value)),'applicable':applicable,'explanation':reason,'components':components}


def evaluate_combination(observation,config):
    denominator=sum(abs(s.weight) for s in config.theories if s.enabled)
    result=[]
    for card in sorted(observation.legal_actions):
        terms=[]
        for spec in config.theories:
            term=evaluate_theory(observation,card,spec)
            term.update(weight=spec.weight,contribution=term['value']*spec.weight/denominator if denominator else 0)
            terms.append(term)
        result.append({'card':card,'score':sum(t['contribution'] for t in terms),'terms':terms})
    return result


def _definition(id,name,description,information,applicability,parameters,relationship,evaluation):
    return TheoryDefinition(id,name,description,"ユーザーが提示した未検証案を検証可能な代理評価へ具体化。有効性の証拠はまだありません。",information,applicability,parameters,relationship,
        ("代理評価の前提が実際の相手行動に合うとは限りません。","複数仮説で同じ情報を重複評価する可能性があります。"),evaluation)


_mode={'default':'preserve','choices':['preserve','consume'],'meaning':'温存 / 早期消費。消費は代理評価の符号を反転'}
register_theory(_definition('reserve_strong','強いカードの温存','高ランクを残して将来の選択肢を保つ。K最大の現行規則でも、強い札が勝つとは限らない。',('手札','ターン'), '最後の選択より前',
    {'mode':_mode,'threshold':{'default':10,'min':1,'max':13,'meaning':'強い札と数える最低ランク'}},'既存Heuristicの残す札の距離項とは別の単純な割合','残る対象札割合×(14−turn)/14。consumeは負値'),lambda o,c,p:_reserve(o,c,p))
register_theory(_definition('reserve_middle','中程度のカードの温存','中ランクを後半の調整に残す。中ランクの札が中位になる保証はない。',('手札','ターン'),'最後の選択より前',
    {'mode':_mode,'center':{'default':7,'min':1,'max':13,'meaning':'中程度の中心ランク'},'width':{'default':2,'min':0,'max':6,'meaning':'中心からの幅'}},'既存Heuristicはランク7から遠い札を残すため、この案と方向が異なる','中心±幅にある残り札の割合×残り選択機会'),lambda o,c,p:_reserve(o,c,p,True))
register_theory(_definition('round_focus','現在ラウンド重視','今のラウンド得点を相手2人の中間へ近づける代理評価。',('公開ラウンド得点','累計得点','未知札','ターン'),'全選択',
    {'mode':{'default':'round','choices':['round','cumulative','both'],'meaning':'ラウンド / 累計 / 両方'}},'ScoreAwareの獲得・回避とHeuristicの距離項に関連','期待目標距離/39の負値。bothはラウンド・累計代理値の平均'),_round)
register_theory(_definition('cumulative_target','累積得点からの逆算','累計点が高いほどよいとはせず、相手の中間目標との距離を評価。',('公開ラウンド得点','累計得点','ターン','未知札'),'全選択',{},'Heuristicの累計過大時の回避を別の距離モデルで検証','相手点固定・仮のラウンド終了時の期待距離を39×残りラウンド数で割り負値化'),_cumulative)
register_theory(_definition('public_memory','公開カードの記憶','公開済み札を除いた分布で中位になる確率を評価。',('手札','任意の公開履歴'),'全選択',
    {'public':{'default':True,'choices':[True,False],'meaning':'この仮説で公開履歴を利用するか'}},'Observation.unseen_cardsと既存カードカウンティングを再利用','未知札から2枚を重複なく一様選択するモデルの中位確率'),_memory)
register_theory(_definition('opponent_targets','相手の目標推定','公開点から獲得・回避を仮定して出札分布を重み付けする。',('公開ラウンド得点','未知札'),'全選択',
    {'strength':{'default':1,'min':0,'max':4,'meaning':'仮定した相手方針の重み。0は一様'}},'ScoreAwareに似た獲得・回避の仮定。学習したOpponent Modelではない','相手得点から仮定した重み付き2札モデルで中位確率を計算し、自分の獲得・回避符号を適用'),_opponents)


def default_theories():
    return TheoryConfig(theories=[TheorySpec(id='reserve_strong'),TheorySpec(id='round_focus')])
