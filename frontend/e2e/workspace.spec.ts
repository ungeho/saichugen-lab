import {test,expect} from '@playwright/test';
const routes=[['/research/stopping-horizon','Stopping Generalization & Budget Horizon Lab'],['/research/stopping','Adaptive Stopping Validation Lab'],['/research/adaptive','Adaptive Sampling & Independent Reference Lab'],['/overview','研究ダッシュボード'],['/recent','最近の実験'],['/play','対戦テーブル'],['/compare','比較実験'],['/arena','Strategy Arena'],['/research/reliability','Decision Reliability Lab'],['/research/decision','Middle-Position Decision Lab'],['/research/stratification','Middle-Position Stratification Lab'],['/research/middle','Middle-Position Control Lab'],['/research/zigzag','Zigzag Strategy Lab'],['/research/theory','Theory Lab'],['/research/evolution','Strategy Evolution'],['/experiments/design','Experimental Design Lab'],['/experiments/evidence','Evidence Accumulation Lab'],['/experiments/evaluation','Evaluation Lab'],['/experiments/quality','探索品質'],['/reference/rules','ゲームルール'],['/reference/algorithms','アルゴリズム図鑑']];
test('全画面の直接アクセス・再読込・旧URL・404は実験を開始しない',async({page})=>{
 const posts:string[]=[];page.on('request',r=>{if(r.method()==='POST')posts.push(r.url());});
 for(const [url,title] of routes){await page.goto(url);await expect(page.getByLabel('現在地').getByRole('heading')).toHaveText(title);await page.reload();await expect(page.getByLabel('現在地').getByRole('heading')).toHaveText(title);}
 await page.goto('/');await expect(page.getByLabel('現在地')).toContainText('対戦テーブル');await page.goto('/missing');await expect(page.getByLabel('現在地')).toContainText('404');expect(posts).toEqual([]);
});
test('カテゴリ・グループ・検索・戻る進む・最近の画面を使える',async({page})=>{
 await page.goto('/');const top=page.getByRole('navigation',{name:'上位カテゴリ'}),side=page.getByRole('navigation',{name:'すべての画面'});
 expect(await top.getByRole('button').count()).toBe(5);const boxes=await top.getByRole('button').evaluateAll(nodes=>nodes.map(n=>n.getBoundingClientRect().top));expect(new Set(boxes).size).toBe(1);
 const group=side.getByRole('button',{name:'中間順位・意思決定研究',exact:true});await expect(group).toHaveAttribute('aria-expanded','true');await expect(page.locator('#middle-pages').getByRole('button')).toHaveCount(7);
 await group.click();await page.reload();await expect(group).toHaveAttribute('aria-expanded','false');await group.click();
 await page.getByLabel('画面を検索').fill('信頼性');await expect(side.getByRole('button',{name:'Decision Reliability Lab',exact:true})).toBeVisible();await side.getByRole('button',{name:'Decision Reliability Lab',exact:true}).click();await expect(page).toHaveURL(/research\/reliability$/);await expect(side.getByRole('button',{name:'Decision Reliability Lab',exact:true})).toHaveAttribute('aria-current','page');
 await top.getByRole('button',{name:'資料',exact:true}).click();await expect(page).toHaveURL(/reference\/rules$/);await page.goBack();await expect(page).toHaveURL(/research\/reliability$/);await page.goForward();await expect(page).toHaveURL(/reference\/rules$/);
 await page.getByText('最近使用した画面',{exact:true}).click();await expect(page.getByRole('button',{name:'最近: Decision Reliability Lab',exact:true})).toBeVisible();
 await page.goto('/overview');await expect(page.locator('.workspace-directory a')).toHaveCount(21);
 const stored=await page.evaluate(()=>JSON.parse(localStorage.getItem('saichugen.workspace.recent')!));expect(stored.every((x:unknown)=>typeof x==='string'&&routes.some(([path])=>path.endsWith(x as string))||['game','rules','overview'].includes(x as string))).toBeTruthy();
});
test('モバイルメニューのキーボード操作と対戦状態の保持',async({page})=>{
 await page.goto('/');await page.getByRole('button',{name:'新しいゲーム',exact:true}).click();await expect(page.locator('.hand .card')).toHaveCount(17);
 await page.setViewportSize({width:390,height:844});const menu=page.getByRole('button',{name:'画面メニューを開く',exact:true});await menu.focus();await page.keyboard.press('Enter');await expect(page.getByRole('button',{name:'画面メニューを閉じる',exact:true})).toHaveAttribute('aria-expanded','true');
 const rule=page.getByRole('navigation',{name:'すべての画面'}).getByRole('button',{name:'ゲームルール',exact:true});await rule.focus();await page.keyboard.press('Escape');await expect(menu).toBeFocused();await page.keyboard.press('Space');await rule.click();await expect(page).toHaveURL(/reference\/rules$/);
 await page.goBack();await expect(page.locator('.hand .card')).toHaveCount(17);await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
 await page.screenshot({path:'../research-local/phase31/mobile.png',fullPage:true});await page.setViewportSize({width:1440,height:1000});await page.goto('/overview');await page.screenshot({path:'../research-local/phase31/desktop.png',fullPage:true});
});
test('最近の実験は実履歴と取得エラーを区別する',async({page})=>{
 const histories=['/api/arena/studies','/api/stratification/jobs','/api/middle/jobs','/api/zigzag/plans','/api/evolution/experiments','/api/design/plans','/api/evidence/series','/api/evaluation/studies','/api/quality-studies'];
 await page.route('**/api/**',route=>histories.includes(new URL(route.request().url()).pathname)?route.fulfill({json:[]}):route.continue());
 await page.route('**/api/reliability/jobs',route=>route.fulfill({json:[{id:'workspace-example',status:'Cancelled',created_at:'2026-10-14T00:00:00Z'}]}));
 await page.route('**/api/decision/jobs',route=>route.fulfill({status:503,json:{detail:'test error'}}));await page.goto('/recent');await expect(page.getByRole('region',{name:'最近の実験'})).toContainText('workspace-example');await expect(page.getByRole('region',{name:'最近の実験'}).getByRole('alert')).toContainText('Middle-Position Decision Lab');
});
test('実行中の履歴を離れても自動停止せず再選択して監視できる',async({page})=>{
 // 通信境界で長時間ジョブを再現。計算を無駄に実行せずUIの離脱契約を確認する。
 const job={id:'workspace-running',status:'Running',positions:[],progress:0,elapsed_seconds:0,condition_hash:'workspace-test'};
 const posts:string[]=[];page.on('request',r=>{if(r.method()==='POST')posts.push(r.url());});
 await page.route('**/api/reliability/jobs',route=>route.fulfill({json:[job]}));
 await page.route('**/api/reliability/jobs/workspace-running',route=>route.fulfill({json:job}));
 await page.goto('/research/reliability');const panel=page.getByRole('region',{name:'Decision Reliability Lab'});
 await panel.getByLabel('信頼性の保存履歴').selectOption(job.id);await expect(panel.getByRole('status').first()).toContainText('Running');
 await page.getByRole('navigation',{name:'上位カテゴリ'}).getByRole('button',{name:'概要',exact:true}).click();await expect(page).toHaveURL(/overview$/);await page.goBack();
 await panel.getByLabel('信頼性の保存履歴').selectOption(job.id);await expect(panel.getByRole('status').first()).toContainText('Running');expect(posts).toEqual([]);
});
