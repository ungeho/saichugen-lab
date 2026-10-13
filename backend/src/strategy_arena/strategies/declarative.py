"""任意コードを含まない、検証済み演算だけの戦略定義。"""
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from random import Random
from typing import Literal, Annotated
import json
import sqlite3

from pydantic import BaseModel, ConfigDict, Field, model_validator
from dataclasses import asdict,replace
from .theories import TheoryConfig
from .theory_policy import TheoryPolicy, TheorySearch
from .hybrid import HybridSearch
from .descriptions import AlgorithmDescription


class ParentReference(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id:str=Field(pattern=r'^[a-z][a-z0-9_]{2,63}$')
    version:str=Field(pattern=r'^\d+\.\d+\.\d+$',max_length=32)
    definition_hash:str=Field(pattern=r'^[a-f0-9]{64}$')


Weight=Annotated[float,Field(strict=True,ge=-2,le=2,allow_inf_nan=False)]
Text=Annotated[str,Field(min_length=1,max_length=1000)]


class SituationRule(BaseModel):
    model_config=ConfigDict(extra='forbid')
    phase:Literal['any','early','middle','late']='any'
    score_position:Literal['any','low','middle','high','tied']='any'
    round_min:int=Field(default=1,strict=True,ge=1,le=5)
    round_max:int=Field(default=5,strict=True,ge=1,le=5)
    weights:dict[str,Weight]=Field(min_length=1,max_length=6)
    explanation:str=Field(min_length=1,max_length=500)

    @model_validator(mode='after')
    def valid(self):
        from math import isfinite
        if self.round_min>self.round_max or any(not isfinite(w) or not -2<=w<=2 for w in self.weights.values()):
            raise ValueError('局面条件または重みの範囲が不正です')
        return self


class StrategyDefinition(BaseModel):
    model_config=ConfigDict(extra='forbid')
    schema_version:Literal[1]=1
    id:str=Field(pattern=r'^[a-z][a-z0-9_]{2,63}$')
    name:str=Field(min_length=1,max_length=80)
    version:str=Field(pattern=r'^\d+\.\d+\.\d+$',max_length=32)
    creator:str=Field(min_length=1,max_length=100)
    description:str=Field(min_length=1,max_length=2000)
    hypothesis:str=Field(min_length=1,max_length=2000)
    rationale:str=Field(min_length=1,max_length=2000)
    expected_strengths:list[Text]=Field(min_length=1,max_length=8)
    expected_weaknesses:list[Text]=Field(min_length=1,max_length=8)
    difference_from_existing:str=Field(min_length=1,max_length=2000)
    theory_config:TheoryConfig
    rules:list[SituationRule]=Field(default_factory=list,max_length=12)
    selection:Literal['theory','theory_search','theory_search_adaptive','uniform','heuristic','adaptive','combined']='theory'
    total_budget:int|None=Field(default=None,strict=True,ge=1,le=256)
    continuation:Literal['Random','Greedy','Conservative','ScoreAware','Heuristic']='Random'
    seed_mode:Literal['evaluator_rng','fixed_policy']='evaluator_rng'
    fixed_policy_seed:int|None=Field(default=None,strict=True,ge=0,le=9007199254740991)
    parent:ParentReference|None=None
    change_summary:str=Field(default='初期候補',max_length=1000)
    change_reason:str=Field(default='未検証の仮説を比較するため',max_length=1000)
    created_at:datetime
    definition_hash:str|None=None

    @model_validator(mode='after')
    def valid(self):
        if (self.selection=='theory')!=(self.total_budget is None):
            raise ValueError('探索だけに総予算が必要です')
        if self.selection=='theory' and self.continuation!='Random':
            raise ValueError('直接選択には継続戦略を適用しません')
        if self.selection in ('uniform','heuristic','adaptive','combined') and (self.rules or self.theory_config.theories):
            raise ValueError('既存探索方式へ適用しないTheoryや局面規則を含めることはできません')
        if (self.seed_mode=='fixed_policy')!=(self.fixed_policy_seed is not None):
            raise ValueError('固定方策seedはfixed_policy方式にだけ指定します')
        ids={s.id for s in self.theory_config.theories}
        if any(set(r.weights)-ids for r in self.rules):raise ValueError('局面規則は定義済みTheoryの重みだけを変更できます')
        if self.parent and self.parent.id==self.id and self.parent.version==self.version:
            raise ValueError('自分自身を親にできません')
        if self.created_at.tzinfo is None:raise ValueError('作成日時にタイムゾーンが必要です')
        self.created_at=self.created_at.astimezone(timezone.utc)
        digest=sha256(json.dumps(self.model_dump(mode='json',exclude={'definition_hash'}),sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
        if self.definition_hash is not None and self.definition_hash!=digest:raise ValueError('定義ハッシュが一致しません')
        self.definition_hash=digest
        return self

    @property
    def reference(self):return self.id+'@'+self.version


def score_position(observation):
    scores=observation.game_scores;own=scores[observation.player]
    if sum(s==own for s in scores)>1:return 'tied'
    return 'low' if own<sorted(scores)[1] else 'high' if own>sorted(scores)[1] else 'middle'


def resolved_theories(definition,observation):
    config=definition.theory_config.model_copy(deep=True)
    phase='early' if observation.turn<5 else 'middle' if observation.turn<10 else 'late'
    position=score_position(observation);round_number=observation.turn//3+1
    matched=None
    for index,rule in enumerate(definition.rules):
        if rule.phase in ('any',phase) and rule.score_position in ('any',position) and rule.round_min<=round_number<=rule.round_max:
            config=TheoryConfig.model_validate({**config.model_dump(),'theories':[{**s.model_dump(),'weight':rule.weights.get(s.id,s.weight)} for s in config.theories]})
            matched=index;break
    return config,matched


class DeclarativeStrategy:
    def __init__(self,definition):
        self.definition=definition.model_copy(deep=True)
        self.name,self.version=definition.id,definition.version

    @property
    def parameters(self):return {'definition_hash':self.definition.definition_hash,'strategy_id':self.name,'version':self.version}

    def choose(self,observation,rng):return self._choose(observation,rng,False)
    def choose_detailed(self,observation,rng):return self._choose(observation,rng,True)

    def _choose(self,observation,rng,capture):
        definition=self.definition
        config,matched=resolved_theories(definition,observation)
        if definition.seed_mode=='fixed_policy':
            material=json.dumps(asdict(observation),sort_keys=True,separators=(',',':'))
            rng=Random(int.from_bytes(sha256((str(definition.fixed_policy_seed)+material).encode()).digest(),'big'))
        if definition.selection=='theory':strategy=TheoryPolicy(config)
        elif definition.selection.startswith('theory_search'):
            strategy=TheorySearch(config,definition.selection.endswith('adaptive'),definition.total_budget,definition.continuation)
        else:strategy=HybridSearch(definition.selection,definition.total_budget,definition.continuation)
        decision=strategy.choose_detailed(observation,rng) if capture else strategy.choose(observation,rng)
        if decision.card not in observation.legal_actions:raise ValueError('宣言戦略が非合法手を返しました')
        if capture and decision.details:
            meta={**(decision.details.optional_metadata or {}),'declarative':{'id':self.name,'version':self.version,'definition_hash':definition.definition_hash,'matched_rule':matched,'resolved_theories':config.model_dump(),'seed_mode':definition.seed_mode}}
            decision=replace(decision,details=replace(decision.details,optional_metadata=meta,reasoning=(f'未検証の宣言戦略 {definition.name}。適用規則 {matched if matched is not None else "基本設定"}。',*decision.details.reasoning)))
        return decision


def builtin_definitions():
    directory=Path(__file__).resolve().parents[4]/'strategy-definitions'
    return [StrategyDefinition.model_validate_json(p.read_text(encoding='utf-8')) for p in sorted(directory.glob('*.json'))]


def description(definition):
    return AlgorithmDescription(tagline=definition.hypothesis,overview=definition.description,
        steps=('観測から列挙型の局面条件を照合。最初に一致した規則を適用。','許可されたTheoryと探索設定だけで選択。'),
        information=('本人の手札・公開履歴・得点・ターン。評価用配札seedは受け取らない。',),
        strengths=tuple(definition.expected_strengths),weaknesses=tuple(definition.expected_weaknesses),
        randomness='評価者の方策rngまたは定義内の固定方策seed。配札rngとは独立。',implementation='宣言JSONを検証済み評価器へ変換。任意コード実行なし。',
        notes=('未検証の仮説。強さの保証ではありません。','定義ハッシュ '+definition.definition_hash))


class DefinitionStore:
    """追記型。既存の実験テーブルや他の定義を更新しない。"""
    def __init__(self,path):
        self.path=path
        with sqlite3.connect(path) as db:db.execute('CREATE TABLE IF NOT EXISTS strategy_definitions (id TEXT, version TEXT, digest TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(id,version))')
        for definition in builtin_definitions():self.add(definition)

    def list(self):
        with sqlite3.connect(self.path) as db:return [json.loads(r[0]) for r in db.execute('SELECT payload FROM strategy_definitions ORDER BY id,version')]

    def get(self,reference):
        parts=reference.rsplit('@',1)
        if len(parts)!=2:raise ValueError('戦略参照はid@versionです')
        with sqlite3.connect(self.path) as db:row=db.execute('SELECT payload FROM strategy_definitions WHERE id=? AND version=?',parts).fetchone()
        if not row:raise ValueError('未登録の戦略版です')
        return StrategyDefinition.model_validate_json(row[0])

    def add(self,definition):
        # 親は既存版の固定ハッシュだけ。前向き参照不可のため循環を作れない。
        if definition.parent:
            parent=self.get(definition.parent.id+'@'+definition.parent.version)
            if parent.definition_hash!=definition.parent.definition_hash:raise ValueError('親のハッシュが一致しません')
        with sqlite3.connect(self.path) as db:
            row=db.execute('SELECT digest FROM strategy_definitions WHERE id=? AND version=?',(definition.id,definition.version)).fetchone()
            if row:
                if row[0]!=definition.definition_hash:raise ValueError('同じID・版の定義を上書きできません。新しい版にしてください')
                return definition
            db.execute('INSERT INTO strategy_definitions VALUES (?,?,?,?)',(definition.id,definition.version,definition.definition_hash,definition.model_dump_json()))
        return definition
