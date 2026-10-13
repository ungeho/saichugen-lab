"""候補生成、評価、選抜、採用を分離した追記型の進化実験。"""
from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
from random import Random
from threading import Lock
from typing import Literal
from uuid import uuid4
import json
import sqlite3

from pydantic import BaseModel, ConfigDict, Field, model_validator
from .arena import ArenaRequest, ArenaPlan, arena_estimate, compare_arena, PARTITIONS
from .quality_statistics import decision_sources,complete_deals,paired_deal_differences
from .evaluation_statistics import fixed_evidence
from ..strategies.declarative import StrategyDefinition

BASELINE = '83fc2f1fb2c79892a463d75783cbe9c46c73df62'
Stage = Literal['development', 'validation', 'final']


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def behavior(definition):
    data = definition.model_dump(mode='json')
    return {k: data[k] for k in ('theory_config', 'rules', 'selection', 'total_budget', 'continuation', 'seed_mode', 'fixed_policy_seed')}


def changes(parent, child):
    a, b = behavior(parent), behavior(child)
    return {key: {'before': a[key], 'after': b[key]} for key in a if a[key] != b[key]}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Generation(StrictModel):
    parent: str
    seed: int = Field(default=42, strict=True, ge=0, le=2**32-1)
    count: int = Field(default=2, strict=True, ge=1, le=4)
    delta: float = Field(default=.25, strict=True, gt=0, le=1, allow_inf_nan=False)
    operations: list[Literal['weight', 'toggle', 'rule_weight', 'add_rule', 'remove_rule', 'search', 'budget']] = Field(default_factory=lambda: ['weight'], min_length=1, max_length=7)
    created_at: datetime
    first_patch: int = Field(default=1, strict=True, ge=1, le=999999)

    @model_validator(mode='after')
    def valid(self):
        if self.created_at.tzinfo is None:
            raise ValueError('作成日時にタイムゾーンが必要です')
        self.created_at = self.created_at.astimezone(timezone.utc)
        return self


def generate(parent, request):
    """生成専用rng。評価結果・配札を入力にしない。登録も対戦もしない。"""
    rng = Random(request.seed)
    output, seen = [], {digest(behavior(parent))}
    for _ in range(200):
        data = parent.model_dump(mode='json', exclude={'definition_hash'})
        operation = rng.choice(request.operations)
        specs = data['theory_config']['theories']
        if operation in ('weight', 'toggle', 'add_rule', 'rule_weight') and not specs:
            continue
        if operation == 'weight':
            target = rng.choice(specs)
            target['weight'] = round(max(-2, min(2, target['weight'] + rng.choice([-1, 1])*request.delta)), 6)
        elif operation == 'toggle':
            target = rng.choice(specs)
            target['enabled'] = not target['enabled']
        elif operation == 'rule_weight':
            if not data['rules']: continue
            rule = rng.choice(data['rules']); key = rng.choice(list(rule['weights']))
            rule['weights'][key] = round(max(-2, min(2, rule['weights'][key] + rng.choice([-1, 1])*request.delta)), 6)
        elif operation == 'add_rule':
            if len(data['rules']) >= 12: continue
            target = rng.choice(specs)
            data['rules'].insert(0, {'phase': rng.choice(['early', 'middle', 'late']), 'weights': {target['id']: round(max(-2, min(2, target['weight']+request.delta)), 6)}, 'explanation': '生成候補：局面別の重み変更を検証する'})
        elif operation == 'remove_rule':
            if not data['rules']: continue
            data['rules'].pop(rng.randrange(len(data['rules'])))
        elif operation == 'search':
            data['selection'] = rng.choice(['theory', 'theory_search', 'theory_search_adaptive'])
            data['total_budget'] = None if data['selection'] == 'theory' else 32
            data['continuation'] = 'Random'
        elif operation == 'budget':
            if data['total_budget'] is None: continue
            data['total_budget'] = max(1, min(256, data['total_budget'] + rng.choice([-16, 16])))
        major, minor, _ = parent.version.split('.')
        data.update(version=f'{major}.{minor}.{request.first_patch+len(output)}', created_at=request.created_at.isoformat(),
                    parent={'id': parent.id, 'version': parent.version, 'definition_hash': parent.definition_hash},
                    creator='数値・構造生成器 / Phase 22', change_summary=f'{operation}を変更',
                    change_reason=f'生成seed {request.seed}。変更の寄与を独立評価する未検証候補')
        child = StrategyDefinition.model_validate(data)
        key = digest(behavior(child))
        if key in seen: continue
        seen.add(key); output.append(child)
        if len(output) == request.count: break
    if len(output) != request.count:
        raise ValueError('重複しない候補が不足しています。変更方式か候補数を変えてください')
    return output


class Criteria(StrictModel):
    min_deals: int = Field(default=10, strict=True, ge=10, le=20)
    min_difference: float = Field(default=0., strict=True, ge=0, le=2, allow_inf_nan=False)
    max_time_ratio: float = Field(default=2., strict=True, ge=1, le=20, allow_inf_nan=False)
    min_opponent_compositions: int = Field(default=1, strict=True, ge=1, le=2)


class EvolutionRequest(StrictModel):
    multiplicity_policy: Literal['bonferroni_fixed'] = 'bonferroni_fixed'
    name: str = Field(default='戦略進化実験', min_length=1, max_length=100)
    parent: str
    children: list[str] = Field(min_length=1, max_length=4)
    opponents: tuple[str, str] = ('Random', 'Heuristic')
    deals: int = Field(default=2, strict=True, ge=1, le=20)
    development_offset: int = Field(default=300, strict=True, ge=0, le=999980)
    validation_offset: int = Field(default=300, strict=True, ge=0, le=999980)
    final_offset: int = Field(default=300, strict=True, ge=0, le=999980)
    policy_seed: int = Field(default=42, strict=True, ge=0, le=2**32-1)
    include_expensive: bool = Field(default=False, strict=True)
    timeout_seconds: int = Field(default=180, strict=True, ge=1, le=300)
    criteria: Criteria = Field(default_factory=Criteria)
    hypothesis: str = Field(min_length=1, max_length=3000)
    expected_effect: str = Field(min_length=1, max_length=2000)
    side_effects: str = Field(min_length=1, max_length=2000)


class StageRequest(StrictModel):
    children: list[str] = Field(min_length=1, max_length=4)


class Adoption(StrictModel):
    child: str
    decision: Literal['Promoted', 'Rejected', 'Inconclusive']
    reason: str = Field(min_length=1, max_length=2000)


def assessment(criteria, stage, child):
    comparison = stage['comparisons'][child]
    settings = stage['result']['summary']['settings']
    parent = settings[0]; candidate = next(s for s in settings if s['reference'] == child)
    reasons = []
    if stage['result']['status'] != 'completed': reasons.append('評価が未完了です')
    if not comparison['comparable']: reasons.extend(comparison['reasons'])
    if comparison['independent_deals'] < criteria.min_deals: reasons.append('独立配札が採用基準未満です')
    ci = comparison.get('ci95')
    if ci is None: reasons.append('対応報酬差の区間が未提供です')
    elif ci[0] <= criteria.min_difference: reasons.append('区間下限が改善基準を超えていません')
    if comparison.get('difference') is None or comparison['difference'] <= criteria.min_difference: reasons.append('対応報酬差が改善基準を超えていません')
    a, b = parent['decision_ms']['mean'], candidate['decision_ms']['mean']
    if a is None or b is None or b > max(a, .001)*criteria.max_time_ratio: reasons.append('判断時間が基準外または不明です')
    if criteria.min_opponent_compositions > 1: reasons.append('相手構成は1種類だけです。複数構成の証拠が不足しています')
    return {'passed': not reasons, 'reasons': reasons, 'comparison': comparison,
            'parent_decision_ms': a, 'child_decision_ms': b}


class Evolution:
    def __init__(self, store, definitions, jobs):
        self.store, self.definitions, self.jobs = store, definitions, jobs
        self.lock = Lock()
        with closing(sqlite3.connect(store.path)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS evolution_experiments (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS evolution_events (seq INTEGER PRIMARY KEY AUTOINCREMENT, experiment_id TEXT NOT NULL, payload TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS evolution_final_seeds (seed INTEGER PRIMARY KEY, experiment_id TEXT NOT NULL)')

    def event(self, identifier, value):
        with closing(sqlite3.connect(self.store.path)) as db, db:
            db.execute('INSERT INTO evolution_events(experiment_id,payload) VALUES (?,?)', (identifier, json.dumps({'created_at': now(), **value})))

    def raw(self, identifier):
        with closing(sqlite3.connect(self.store.path)) as db:
            row = db.execute('SELECT payload FROM evolution_experiments WHERE id=?', (identifier,)).fetchone()
            if not row: raise KeyError(identifier)
            events = [json.loads(r[0]) for r in db.execute('SELECT payload FROM evolution_events WHERE experiment_id=? ORDER BY seq', (identifier,))]
        return json.loads(row[0]), events

    def create(self, request):
        if len(set(request.children)) != len(request.children): raise ValueError('候補が重複しています')
        parent = self.definitions.get(request.parent)
        children = [self.definitions.get(r) for r in request.children]
        seen = {digest(behavior(parent))}
        for child in children:
            if not child.parent or child.parent.model_dump() != {'id': parent.id, 'version': parent.version, 'definition_hash': parent.definition_hash}:
                raise ValueError('すべての子は指定した親版・hashから派生する必要があります')
            key = digest(behavior(child))
            if key in seen: raise ValueError('親または他候補と同じ行動設定です')
            seen.add(key)
        plans = {}
        for stage in ('development', 'validation', 'final'):
            plans[stage] = ArenaRequest(participants=[request.parent, *request.children], opponents=request.opponents, deals=request.deals,
                seed_partition=stage, start_offset=getattr(request, stage+'_offset'), policy_seed=request.policy_seed,
                include_expensive=request.include_expensive, timeout_seconds=request.timeout_seconds).resolve(self.definitions).model_dump(mode='json')
        settings = request.model_dump(mode='json')
        payload = {'schema_version':1, 'assessment_version':'evolution-policy-v2', 'baseline_commit': BASELINE, 'created_at': now(), 'settings': settings, 'plans': plans,
                   'parent': parent.model_dump(mode='json'), 'children': [d.model_dump(mode='json') for d in children],
                   'changes': {d.reference: changes(parent, d) for d in children}}
        payload['config_hash'] = digest({k: v for k, v in payload.items() if k != 'created_at'})
        identifier = str(uuid4())
        with closing(sqlite3.connect(self.store.path)) as db, db:
            db.execute('INSERT INTO evolution_experiments VALUES (?,?)', (identifier, json.dumps(payload)))
        return self.get(identifier)

    def get(self, identifier):
        raw, events = self.raw(identifier)
        stages = {}
        for e in events:
            if e['type'] == 'stage_started':
                result = self.jobs.get(e['arena_id'], True)
                parent = ArenaPlan.model_validate(result['config']).settings[0]
                comparisons = {}
                for setting in ArenaPlan.model_validate(result['config']).settings[1:]:
                    comparisons[setting.reference] = compare_arena(result, result, parent.identifier, setting.identifier)
                stages[e['stage']] = {'arena_id': e['arena_id'], 'selected_children': e['children'], 'fresh_deals':e.get('fresh_deals'), 'result': result, 'comparisons': comparisons}
        criteria = Criteria.model_validate(raw['settings']['criteria'])
        candidates = []
        for child in raw['children']:
            reference = child['id']+'@'+child['version']; state = 'Candidate'; evidence = {}
            if 'development' in stages and reference in stages['development']['comparisons'] and stages['development']['result']['status']=='completed': state = 'Development Tested'
            for stage in ('validation', 'final'):
                if stage in stages and reference in stages[stage]['comparisons']:
                    evidence[stage] = assessment(criteria, stages[stage], reference)
                    if raw['settings'].get('multiplicity_policy')=='bonferroni_fixed':
                        record=stages[stage]['result'];plan=ArenaPlan.model_validate(record['config'])
                        target=next(s for s in plan.settings if s.reference==reference)
                        samples=paired_deal_differences(complete_deals(plan,record['results'],plan.settings[0]),complete_deals(plan,record['results'],target))
                        corrected=fixed_evidence(samples.values(),comparisons=len(stages[stage]['selected_children']),
                            completed=record['status']=='completed' and len(samples)==len(plan.deal_seeds),confirmatory=stages[stage]['fresh_deals'] is True)
                        evidence[stage]['multiplicity']=corrected
                        if corrected['decision']!='positive' or not corrected.get('interval') or corrected['interval'][0]<=criteria.min_difference:
                            evidence[stage]['passed']=False
                            evidence[stage]['reasons'].append('固定標本Bonferroni補正後の正の差を確認できません')
                    previous = stages.get('development' if stage=='validation' else 'validation')
                    current = stages[stage]['result']
                    if not previous or decision_sources(previous['result']) != decision_sources(current) or any(previous['result'].get(k)!=current.get(k) for k in ('rule_version','reward_version','information_condition','runner_seed_scheme')):
                        evidence[stage]['passed'] = False
                        evidence[stage]['reasons'].append('前段階と評価器・ルール・報酬・情報条件が一致しません')
                    state = 'Validation Passed' if evidence[stage]['passed'] else 'Inconclusive'
            decisions = [e for e in events if e['type']=='decision' and e['child']==reference]
            if decisions: state = decisions[-1]['decision']
            candidates.append({'reference': reference, 'state': state, 'evidence': evidence})
        return {'id': identifier, **raw, 'events': events, 'stages': stages, 'candidates': candidates,
                'estimates': {s: arena_estimate(ArenaPlan.model_validate(p)) for s, p in raw['plans'].items()}}

    def history(self):
        with closing(sqlite3.connect(self.store.path)) as db:
            return [{'id': i, 'name': json.loads(p)['settings']['name'], 'created_at': json.loads(p)['created_at']} for i, p in db.execute('SELECT id,payload FROM evolution_experiments ORDER BY rowid DESC')]

    def start(self, identifier, stage, selected):
        if stage not in PARTITIONS: raise ValueError('未知の評価段階です')
        with self.lock:
            with self.jobs.lock:
                if self.jobs.closed or self.jobs.active is not None:
                    raise RuntimeError('Arena評価は1件ずつ実行してください。開始前のため段階を消費していません')
            view = self.get(identifier)
            if any(e['type']=='stage_requested' and e['stage']==stage for e in view['events']): raise ValueError('この段階は開始済みです。結果を上書きしません')
            if len(set(selected.children)) != len(selected.children): raise ValueError('候補が重複しています')
            allowed = {c['reference']: c for c in view['candidates']}
            if not set(selected.children) <= allowed.keys(): raise ValueError('実験外の候補です')
            if any(allowed[c]['state'] in ('Promoted', 'Rejected') for c in selected.children): raise ValueError('採用・棄却済み候補は評価できません')
            if stage == 'development' and set(selected.children)!=set(allowed): raise ValueError('開発評価は生成候補全体を評価してください')
            if stage != 'development':
                previous = view['stages'].get('development' if stage=='validation' else 'validation')
                if not previous or previous['result']['status']!='completed' or not set(selected.children)<=set(previous['selected_children']): raise ValueError('前段階の完了と候補の明示選抜が必要です')
            if stage == 'final' and any(not allowed[c]['evidence'].get('validation',{}).get('passed') for c in selected.children): raise ValueError('最終評価は検証基準を満たした候補だけです')
            plan = ArenaPlan.model_validate(view['plans'][stage])
            plan = ArenaPlan.model_validate({**plan.model_dump(mode='json'), 'settings': [plan.settings[0].model_dump(mode='json'), *[s.model_dump(mode='json') for s in plan.settings[1:] if s.reference in selected.children]]})
            # 予約と履歴は評価開始前に確定。失敗しても最終seedを再利用しない。
            with closing(sqlite3.connect(self.store.path)) as db, db:
                db.execute('BEGIN IMMEDIATE')
                if stage == 'final':
                    for _, payload in db.execute('SELECT id,payload FROM experiments'):
                        config = json.loads(payload).get('config', {})
                        if config.get('seed_partition')=='final' and set(config.get('deal_seeds',[])) & set(plan.deal_seeds): raise ValueError('最終評価seedが既存の実験で使用済みです')
                    try:
                        db.executemany('INSERT INTO evolution_final_seeds VALUES (?,?)', [(s, identifier) for s in plan.deal_seeds])
                    except sqlite3.IntegrityError: raise ValueError('最終評価seedは予約・使用済みです') from None
                db.execute('INSERT INTO evolution_events(experiment_id,payload) VALUES (?,?)', (identifier, json.dumps({'type':'stage_requested','stage':stage,'children':selected.children,'created_at':now()})))
            try: result = self.jobs.submit(plan)
            except Exception:
                self.event(identifier, {'type':'stage_failed_to_start','stage':stage})
                raise
            prior_seeds=set()
            for previous_id,payload in self.store.iter_experiments():
                if previous_id!=result['id']:prior_seeds.update(payload.get('config',{}).get('deal_seeds',[]))
            self.event(identifier, {'type':'stage_started','stage':stage,'children':selected.children,'arena_id':result['id'],'fresh_deals':not bool(set(plan.deal_seeds)&prior_seeds)})
            return self.get(identifier)

    def decide(self, identifier, request):
        with self.lock:
            view = self.get(identifier)
            candidate = next((c for c in view['candidates'] if c['reference']==request.child), None)
            if candidate is None: raise ValueError('実験外の候補です')
            if candidate['state'] in ('Promoted','Rejected'): raise ValueError('確定した採用・棄却は変更できません')
            if any(s['result']['status'] in ('running','cancelling') for s in view['stages'].values()): raise ValueError('評価中は採用状態を変更できません')
            if request.decision=='Promoted' and not all(candidate['evidence'].get(stage,{}).get('passed') for stage in ('validation','final')): raise ValueError('検証・最終評価が採用基準を満たしていません')
            self.event(identifier, {'type':'decision', **request.model_dump()})
            return self.get(identifier)

    def proposal(self, identifier):
        """開発結果の集計だけ。最終/検証結果・配札seed・実手札を含めない。"""
        view = self.get(identifier)
        development = view['stages'].get('development')
        if not development or development['result']['status']!='completed': raise ValueError('開発評価の完了が必要です')
        summary = development['result']['summary']
        # 対応配札IDも改善提案へ渡さない。評価用計画と生データを切り離す。
        safe_summary = {'settings':summary['settings'], 'method':summary['method'], 'warning':summary['warning'],
                        'differences':[{k:v for k,v in d.items() if k not in ('matched_deals','first_only_deals','second_only_deals')} for d in summary['differences']]}
        return {'schema_version':1,'parent':view['parent'],'development_summary':safe_summary,
                'opponents':view['settings']['opponents'],'known_weaknesses':view['parent']['expected_weaknesses'],
                'hypothesis':view['settings']['hypothesis'],'allowed_changes':['theory_config','rules','selection','total_budget','continuation','seed_mode','fixed_policy_seed'],
                'instructions':'改善理由と宣言戦略JSONのみを出力。親hashを固定し別版にする。検証・最終結果は生成に使用しない。任意コード・式・shell・fileは禁止。',
                'limitations':'局面別傾向は未計測。対応差と集計だけで詳細な行動傾向を断定しない。'}
