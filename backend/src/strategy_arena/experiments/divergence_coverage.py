"""自然抽出と得点層別抽出を分離する。選択/停止/評価アルゴリズムは変更しない。"""
from collections import Counter
from .campaign_analysis import campaign_summary,summarize,sign
from .calibration_coverage import normalized
from .stratification_analysis import period
from .budget_calibration import completion_audit
from .stopping_analysis import rate_interval

CLASSES=('highest','strict_middle','lowest','tie')


def score_class(scores,player):
    if len(scores)!=3 or player not in (0,1,2):raise ValueError('3席の得点が必要')
    if len(set(scores))<3:return 'tie'
    return 'highest' if scores[player]==max(scores) else 'lowest' if scores[player]==min(scores) else 'strict_middle'


def select_coverage(records,c):
    """有限の事前生成候補だけ。Nは事前指定tuple、Sは事前得点層を使う。"""
    selected=[];slots=[]
    for i,label in enumerate(c.campaign_periods):
        seed=str(c.start_offset+i);turn=min(t for t in c.turns if normalized(period(t))==label)
        source=c.collectors[i%len(c.collectors)];player=i%3
        pool=[]
        for r in records:
            for o in r.get('origins',[r]):
                if str(o['deal_id'])==seed and o['turn']==turn:
                    projected={**r,**o}
                    cls=score_class(projected['game_scores'],o['player'])
                    pool.append((projected,cls))
        target=c.coverage_targets[i] if c.collection_series=='S' else None
        candidates=[r for r,cls in pool if (cls==target if target else r['source']==source and r['player']==player)]
        if c.collection_series=='N' and len(candidates)>1:raise ValueError('自然抽出tupleが重複しています')
        picked=min(candidates,key=lambda r:(c.collectors.index(r['source']),r['player'],r['position_hash'])) if candidates else None
        slot={'ordinal':i,'deal_id':seed,'period':label,'turn':turn,'requested_class':target,
            'fixed_source':source if target is None else None,'fixed_player':player if target is None else None,
            'candidate_observations':len(pool),'available_classes':dict(Counter(cls for _,cls in pool)),
            'status':'selected' if picked else 'collection_missing','position_hash':picked['position_hash'] if picked else None,
            'deal_hash':picked['deal_hash'] if picked else None,'selected_class':score_class(picked['game_scores'],picked['player']) if picked else None}
        slots.append(slot)
        if picked:selected.append({**picked,'coverage_ordinal':i,'collection_series':c.collection_series})
    return selected,slots


def anomalies(positions):
    out=[]
    for p in positions:
        for r in p['adaptive']['rows']:
            fixed=next(x for x in p['adaptive']['rows'] if x['model']==r['model'] and x['repeat']==r['repeat'] and x['method']=='Fixed')
            if r['selected_card']!=fixed['selected_card'] and not r['early_stop']:
                out.append({'position_hash':p['position_hash'],'model':r['model'],'method':r['method'],
                    'reason':'早期停止なしの分岐。seed・共通世界・タイブレーク・直接実行一致を調査してください'})
    return out


def audit_coverage(v):
    slots=v.get('collection_summary',{}).get('coverage_slots',[]) if v.get('collection_summary') else []
    selected=[s for s in slots if s['status']=='selected'];expected=v['config']['deals']
    audit=completion_audit({**v,'config':{**v['config'],'deals':len(selected),'max_positions':len(selected)}})
    checks=audit['checks']
    checks.update(all_collection_slots=len(slots)==expected,
        all_deals_collected=v.get('collection_summary',{}).get('independent_deals')==expected if v.get('collection_summary') else False,
        collection_hashes=sorted(s['deal_hash'] for s in slots if s.get('deal_hash'))==sorted(v['snapshot']['deal_hashes']),
        selected_positions={s['position_hash'] for s in selected}=={p['position_hash'] for p in v['positions']},
        no_unexplained_divergence=not anomalies(v['positions']),
        natural_no_missing=v['config']['collection_series']=='S' or len(selected)==expected)
    return {'checks':checks,'primary_finalized':all(checks.values()),
        'scope':'全配札の収集処理と全選択局面の評価を確認。明示的な層欠測は評価完了数に含めない。Sは探索的のみ。'}


def coverage_report(v):
    from .campaign_analysis import CampaignCriteria
    c=v['config'];series=c['collection_series'];positions=v['positions']
    if any(p['adaptive'].get('collection_series')!=series for p in positions):raise ValueError('N/Sの結果を混合しません')
    criteria=CampaignCriteria(**c['campaign_criteria']);audit=audit_coverage(v);full=audit['primary_finalized']
    base=campaign_summary(positions,criteria,complete=full)
    flags=anomalies(positions)
    for row in base['partial_evidence']:
        p=next(p for p in positions if p['position_hash']==row['position_hash'])
        source=next(r for r in p['adaptive']['rows'] if r['model']==row['model'] and r['method']==row['method'])
        row.update(collection_series=series,player=p['player'],stop_reason=source['stop_reason'],
            selection_gap=source['trace'][-1]['gap'] if source['trace'] else None,
            fixed_final_gap=row['fixed_final_checkpoint']['gap'] if row['fixed_final_checkpoint'] else None,
            selection_information='選択時の標本のみ',additional_information='Fixed最終候補・順位変化・独立Finalは事後分析専用')
        ranking=sorted(row['fixed_estimates'],key=lambda x:(-x['reward'],x['card']['rank'],x['card']['suit']))
        row['selected_rank_at_128']=next(i+1 for i,x in enumerate(ranking) if x['card']==row['selected_card'])
        row['gap_change']=row['fixed_final_gap']-row['selection_gap'] if row['selection_gap'] is not None else None
        row['selection_gap_sign']=sign(row['selection_gap'],criteria.sign_tolerance) if row['selection_gap'] is not None else None
        row['gap_change_sign']=sign(row['gap_change'],criteria.sign_tolerance) if row['gap_change'] is not None else None
        if row['diverged'] and not row['early_stop']:row['category']='anomaly_without_early_stop'
    extra=[]
    if full:
        for method in ('Fixed','Gap-Adaptive','Uncertainty-Adaptive'):
            rs=[r for r in base['partial_evidence'] if r['method']==method]
            for key in ('source','legal_count'):
                for value in sorted({r[key] for r in rs}):
                    extra.append({'method':method,'stratum':key,'value':value,**summarize([r for r in rs if r[key]==value],criteria,method+':'+key+':'+str(value))})
        for result in base['primary'] or []:
            values=[d['diverged'] for d in result['paired_deals']]
            from .campaign_analysis import interval
            result['divergence_bootstrap_interval']=interval(values,criteria,result['method']+':divergence')
            result['divergence_interval']=([0.,0.] if result['method']=='Fixed' else rate_interval(values,2)) if series=='N' else result['divergence_bootstrap_interval']
            result['divergence_interval_method']='独立配札の[0,1]有界平均Hoeffding境界・2主比較Bonferroni（95%）。独立性仮定が必要。' if series=='N' else '選別標本の探索的percentile bootstrap。自然頻度の区間ではない。'
    slots=v.get('collection_summary',{}).get('coverage_slots',[]) if v.get('collection_summary') else []
    done={p['position_hash'] for p in positions};events={r['position_hash'] for r in v.get('runtime_measurements',[])}
    counts={'complete':0,'partial':0,'not_started':0,'collection_missing':0}
    for slot in slots:
        state='collection_missing' if slot['status']=='collection_missing' else 'complete' if slot['position_hash'] in done else 'partial' if slot['position_hash'] in events else 'not_started'
        counts[state]+=1
    if not slots:counts['not_started']=c['deals']
    return {**base,'collection_series':series,'role':'primary_natural' if series=='N' else 'exploratory_selected',
        'primary_finalized':full and series=='N','series_completed':full,
        'primary':base['primary'] if series=='N' else None,'selected_sample_summary':base['primary'] if series=='S' else None,
        'secondary_exploratory':([*(base['secondary_exploratory'] or []),*extra] if full else None),
        'anomalies':flags,'slots':slots,'completion_audit':audit,'completion_counts':counts,
        'extraction_success':{'selected':sum(s['status']=='selected' for s in slots),'requested':c['deals'],
            'rate':sum(s['status']=='selected' for s in slots)/c['deals'] if len(slots)==c['deals'] else None},
        'stratified_coverage':[{'score_class':label,'requested':c['coverage_targets'].count(label),'attempted':sum(s.get('requested_class')==label for s in slots),
            'selected':sum(s.get('requested_class')==label and s['status']=='selected' for s in slots),
            'rate':sum(s.get('requested_class')==label and s['status']=='selected' for s in slots)/c['coverage_targets'].count(label) if c['coverage_targets'].count(label) and sum(s.get('requested_class')==label for s in slots)==c['coverage_targets'].count(label) else None} for label in CLASSES],
        'collection_limit':c['deals']*len(c['collectors'])*len(c['turns'])*3,
        'bias_warning':'Nは事前指定した収集元/席/時点混合に条件付けた自然抽出。ゲーム全局面の一様頻度ではない。' if series=='N' else 'Sは得点層を選別した標本。抽出成功率・分岐率から自然発生頻度を推定しない。',
        'interval_note':'Nの分岐率区間は独立配札の有界平均Hoeffding境界（2比較同時95%、独立性仮定）。分岐0でも上限を0にしない。wall/報酬とSの区間は小標本の探索的bootstrap。',
        'version':'divergence-coverage-v1'}
