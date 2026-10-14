import {RuntimePanel} from '../runtime/RuntimePanel';
import {HorizonPanel} from '../horizon/HorizonPanel';
import {StoppingPanel} from '../stopping/StoppingPanel';
import {AdaptivePanel} from '../adaptive/AdaptivePanel';
import type {ComponentType, ReactNode} from 'react';
import {ReliabilityPanel} from '../reliability/ReliabilityPanel';
import {DecisionPanel} from '../decision/DecisionPanel';
import {StratificationPanel} from '../stratification/StratificationPanel';
import {MiddlePanel} from '../middle/MiddlePanel';
import {ZigzagPanel} from '../zigzag/ZigzagPanel';
import {EvidencePanel} from '../evidence/EvidencePanel';
import {QualityStudyPanel} from '../quality/QualityStudyPanel';
import {TheoryLabPanel} from '../theory/TheoryLabPanel';
import {DesignPanel} from '../design/DesignPanel';
import {EvaluationPanel} from '../evaluation/EvaluationPanel';
import {EvolutionPanel} from '../evolution/EvolutionPanel';
import {StrategyArena} from '../arena/StrategyArena';
import {RulesPage} from '../game/RulesPage';

export const categories = {overview:'概要', play:'対戦・比較', research:'戦略研究', evidence:'実験・証拠', reference:'資料'};
export const groups = {middle:{title:'中間順位・意思決定研究',category:'research'}};
export type PageProps = {views:Record<string,ReactNode>};
// 親の対戦状態を維持する画面だけ、Appが作ったビューを受け取る。
const bound = (id:string) => ({views}:PageProps) => <>{views[id]}</>;
export const screenComponents:Record<string,ComponentType<PageProps>> = {
  overview:bound('overview'), recent:bound('recent'), game:bound('game'), experiments:bound('experiments'), catalog:bound('catalog'),
  runtime:RuntimePanel, horizon:HorizonPanel, stopping:StoppingPanel, adaptive:()=> <AdaptivePanel/>, reliability:ReliabilityPanel, decision:DecisionPanel, stratification:StratificationPanel, middle:MiddlePanel,
  zigzag:ZigzagPanel, theory:TheoryLabPanel, evolution:EvolutionPanel, arena:StrategyArena,
  design:DesignPanel, evidence:EvidencePanel, evaluation:EvaluationPanel, quality:()=> <QualityStudyPanel/>, rules:RulesPage,
};
export type ResearchPage = {id:string;title:string;category:keyof typeof categories;group?:keyof typeof groups;path:string;component:ComponentType<PageProps>;keywords:string;historyApi?:string};
const define = (id:string,title:string,category:ResearchPage['category'],path:string,keywords:string,historyApi?:string,group?:ResearchPage['group']):ResearchPage => ({id,title,category,path,keywords,historyApi,group,component:screenComponents[id]});
export const pages:ResearchPage[] = [
  define('overview','研究ダッシュボード','overview','/overview','dashboard 一覧'),
  define('recent','最近の実験','overview','/recent','recent history 履歴'),
  define('game','対戦テーブル','play','/play','game 人間 AI 観戦'),
  define('experiments','比較実験','play','/compare','comparison 一括 統計'),
  define('arena','Strategy Arena','play','/arena','宣言的 戦略 対戦','/api/arena/studies'),
  define('runtime','Stopping Robustness & Runtime Validation Lab','research','/research/stopping-runtime','停止 頑健性 実時間 runtime','/api/stopping-runtime/jobs','middle'),
  define('horizon','Stopping Generalization & Budget Horizon Lab','research','/research/stopping-horizon','停止 予算上限 horizon','/api/stopping-horizon/jobs','middle'),
  define('stopping','Adaptive Stopping Validation Lab','research','/research/stopping','適応停止 独立検証','/api/stopping/jobs','middle'),
  define('adaptive','Adaptive Sampling & Independent Reference Lab','research','/research/adaptive','適応 サンプリング 独立参照','/api/adaptive/jobs','middle'),
  define('reliability','Decision Reliability Lab','research','/research/reliability','信頼性 予算 乱数','/api/reliability/jobs','middle'),
  define('decision','Middle-Position Decision Lab','research','/research/decision','中間順位 意思決定','/api/decision/jobs','middle'),
  define('stratification','Middle-Position Stratification Lab','research','/research/stratification','中間順位 層別','/api/stratification/jobs','middle'),
  define('middle','Middle-Position Control Lab','research','/research/middle','中間順位 制御','/api/middle/jobs','middle'),
  define('zigzag','Zigzag Strategy Lab','research','/research/zigzag','ジグザグ 戦略','/api/zigzag/plans'),
  define('theory','Theory Lab','research','/research/theory','理論 重み'),
  define('evolution','Strategy Evolution','research','/research/evolution','戦略進化 系譜','/api/evolution/experiments'),
  define('design','Experimental Design Lab','evidence','/experiments/design','実験計画','/api/design/plans'),
  define('evidence','Evidence Accumulation Lab','evidence','/experiments/evidence','証拠 蓄積','/api/evidence/series'),
  define('evaluation','Evaluation Lab','evidence','/experiments/evaluation','評価','/api/evaluation/studies'),
  define('quality','探索品質','evidence','/experiments/quality','quality rollout','/api/quality-studies'),
  define('rules','ゲームルール','reference','/reference/rules','rules 得点 スート'),
  define('catalog','アルゴリズム図鑑','reference','/reference/algorithms','catalog strategy 戦略'),
];
export function validateRegistry(registry:ResearchPage[],components=Object.keys(screenComponents)){
  const ids=new Set<string>(), paths=new Set<string>();
  for(const p of registry){
    if(ids.has(p.id)||paths.has(p.path))throw new Error('画面IDまたはURLが重複しています');
    if(!Object.hasOwn(categories,p.category))throw new Error('未登録カテゴリ');
    if(p.group&&(!Object.hasOwn(groups,p.group)||groups[p.group].category!==p.category))throw new Error('不正なグループ');
    if(!p.component||!components.includes(p.id))throw new Error('未登録コンポーネント');
    if(!p.path.startsWith('/')||p.path.includes('?')||p.path.includes('#'))throw new Error('不正なURL');
    ids.add(p.id);paths.add(p.path);
  }
  if(components.some(id=>!ids.has(id)))throw new Error('未登録画面があります');
}
validateRegistry(pages);
export const findPage = (path:string) => pages.find(p=>p.path===(path==='/'?'/play':path.replace(/\/$/,'')));
export const matchPages = (text:string) => pages.filter(p=>`${p.title} ${p.keywords} ${categories[p.category]}`.toLocaleLowerCase().includes(text.trim().toLocaleLowerCase()));
