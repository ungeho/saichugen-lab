"""Zigzagの登録済みパイロットを既存Design/Evidenceへ接続する。"""
from contextlib import closing
import sqlite3,json
from .design_lab import PlanSpec,now
from .arena import ArenaPlan
from .zigzag_analysis import summarize_traces

STRATEGIES=['Random','Greedy','ScoreAware','Heuristic','Zigzag','Reverse Zigzag']

def zigzag_template():
    return PlanSpec.model_validate({'plan_id':'zigzag-pilot','created_at':now(),'reason':'H1は構造テスト、H2–H5は未検証の探索仮説。H6は公開列の必要条件だけを診断。',
        'hypothesis':'序盤の極端な札の消費と終盤の中央札の保持が、ターン順位・累積順位・終局報酬へどう影響するかを共通配札で診断する。',
        'evaluation':{'name':'Zigzag順位パイロット','participants':STRATEGIES,'opponents':[{'name':'Random / Heuristic','strategies':['Random','Heuristic']},{'name':'Greedy / ScoreAware','strategies':['Greedy','ScoreAware']}],
            'deals':4,'deal_layout':'shared','start_offset':5000,'seed_partition':'development','capture_rank_trace':True,'timeout_seconds':60,'alpha':.05,'minimum_effect':.5},
        'budget':{'max_independent_deals':4,'max_games':288,'max_rollouts':0,'allowed_seconds':60}})


def zigzag_result(design,identifier,version):
    plan=design.get(identifier,version)
    if not plan['spec']['evaluation'].get('capture_rank_trace'):raise ValueError('順位ログを有効にしたPlanが必要です')
    summaries=[]
    running=next((e for e in plan['events'] if e.get('evaluation_id')),None)
    if running:
        result=design.evaluation.get(running['evaluation_id'])
        if plan['state']!='Invalidated':
            for r in result['reports']:
                raw=design.store.get(r['arena_id'])
                summaries.append({'composition':r['name'],'strategies':summarize_traces(ArenaPlan.model_validate(raw['config']),raw['results'])})
    return {'plan':plan,'summaries':summaries,'hypotheses':{'H1':'強弱の交互消費は構造テストで確認する。','H2':'序盤の極端なターン順位は相手依存。','H3':'中央札の保持と実際のターン2位は別。','H4':'累積得点の中間化は厳密中間と同点込みを分離。','H5':'平均終局報酬は同点・共同勝利を含む。','H6':'公開列の必要条件のみ。確率・次の正確な札は推定しない。'},
        'warning':'4配札パイロットでは優劣を断定しない。順位の分布は補助的な記述統計で、多数の区分から有意なものを選ばない。',
        'recommendations':['追加配札は別の登録Planで予算を再確認。','別の相手構成で頑健性を確認。','既知規則・公開履歴推定・通常相手の3条件対策実験は次フェーズ。']}


def zigzag_history(design):
    # 一覧表示で全Planの統計・推薦を再計算しない。
    with closing(sqlite3.connect(design.store.path)) as db:
        rows=db.execute('SELECT id,version,payload FROM design_plans ORDER BY rowid DESC').fetchall()
    return [{'id':i,'version':v} for i,v,p in rows if json.loads(p)['spec']['evaluation'].get('capture_rank_trace')]
