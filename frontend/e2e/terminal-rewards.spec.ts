import {test,expect} from '@playwright/test';

test('終局だけに3席の独立報酬を表示する',async({page})=>{
 await page.goto('/');
 await page.getByRole('button',{name:'新しいゲーム',exact:true}).click();
 await expect(page.getByRole('region',{name:'終局結果',exact:true})).toHaveCount(0);
 for(let i=0;i<15;i++){
  const response=page.waitForResponse(r=>r.url().endsWith('/step'));
  await page.getByRole('button',{name:'AIで1ターン進む',exact:true}).click();
  const game=await(await response).json();
  if(i<14)expect(game.terminal_rewards).toBeNull();
  else{
   expect(game.terminal_rewards.reduce((a:number,b:number)=>a+b,0)).toBe(0);
   const result=page.getByRole('region',{name:'終局結果',exact:true});
   await expect(result).toContainText('累計得点には加算されず');
   await expect(result.locator('tbody tr')).toHaveCount(3);
   const cells=await result.locator('tbody td:last-child').allTextContents();
   expect(cells.map(Number)).toEqual(game.terminal_rewards);
   expect((await result.locator('tbody td:nth-child(2)').allTextContents()).map(Number)).toEqual(game.observation.game_scores);
  }
 }
});

test('実験の5指標と図鑑、平均値グラフを切り替える',async({page})=>{
 await page.goto('/');
 await page.getByRole('button',{name:'比較実験',exact:true}).click();
 await page.getByLabel('独立配札数').fill('2');
 const response=page.waitForResponse(r=>r.url().endsWith('/api/experiments')&&r.request().method()==='POST');
 await page.getByRole('button',{name:'比較実験を実行',exact:true}).click();
 const experiment=await(await response).json();
 for(const value of Object.values(experiment.summary.strategies) as {win_rate:number;sole_win_rate:number;joint_win_rate:number;average_terminal_reward:number}[]){
  expect(value.win_rate).toBeCloseTo(value.sole_win_rate+value.joint_win_rate);
  expect(value.average_terminal_reward).toBeGreaterThanOrEqual(-2);
 }
 await expect(page.locator('.metrics .panel').first()).toContainText('単独勝利率');
 await expect(page.locator('.metrics .panel').first()).toContainText('平均終局報酬');
 await expect(page.getByRole('img',{name:'戦略別平均終局報酬',exact:true})).toBeVisible();
 await page.getByRole('combobox',{name:'平均値の比較指標',exact:true}).selectOption('cumulative');
 await expect(page.getByRole('img',{name:'戦略別平均累計得点',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'アルゴリズム図鑑',exact:true}).click();
 await expect(page.locator('.catalog-statistics')).toContainText('平均終局報酬');
 await expect(page.locator('.catalog-statistics')).toContainText('旧結果から補完');
});

test('分岐の報酬差とルール表を確認する',async({page})=>{
 await page.goto('/');
 await page.getByRole('button',{name:'新しいゲーム',exact:true}).click();
 await page.getByRole('button',{name:'同じ局面でAIを比較',exact:true}).click();
 await page.getByRole('button',{name:'この局面で比較する',exact:true}).click();
 const branch=page.getByRole('region',{name:'分岐シミュレーション',exact:true});
 await branch.getByRole('spinbutton',{name:'分岐の試行回数',exact:true}).fill('4');
 await branch.getByRole('button',{name:'分岐シミュレーションを実行',exact:true}).click();
 await expect(branch.getByRole('status')).toContainText('計算完了');
 await expect(branch.locator('table')).toContainText('平均終局報酬');
 await expect(branch.locator('table')).toContainText('単独 / 共同勝利率');
 await branch.getByRole('combobox',{name:'分岐結果のグラフ指標',exact:true}).selectOption('reward');
 await expect(branch.getByRole('img',{name:'候補カード別の平均終局報酬',exact:true})).toBeVisible();
 await branch.getByText('順位分布・ばらつき・候補間の差',{exact:true}).click();
 await expect(branch).toContainText('平均終局報酬差');
 await page.screenshot({path:'test-results/terminal-rewards-desktop.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});
 await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
 await page.getByRole('button',{name:'ゲームルール',exact:true}).click();
 const rules=page.getByRole('region',{name:'終局報酬のルール',exact:true});
 await expect(rules).toContainText('2021年論文');
 await expect(rules).toContainText('原案との完全一致も未確認');
 await expect(rules.locator('tbody tr')).toHaveCount(3);
 await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
});

test('図鑑の不明な報酬を0として表示しない',async({page})=>{
 await page.route('**/api/algorithms/Random/statistics',route=>route.fulfill({json:{
 name:'Random',note:'テスト用の旧記録',unclassified_experiments:0,groups:[{
 rule_version:'unknown',information_condition:'imperfect',strategy_version:'1',parameters:{},
 opponents:[{name:'Greedy',version:'1'},{name:'Heuristic',version:'1'}],participations:1,match_count:1,wins:1,win_rate:1,
 average_score:8,score_distribution:[{score:8,count:1}],experiment_ids:['old'],average_terminal_reward:null,
 sole_win_rate:1,joint_win_rate:0,reward_games:0,reward_unknown_games:1,reward_sources:{unknown:1},reward_version:null
 }]}}));
 await page.goto('/');
 await page.getByRole('button',{name:'アルゴリズム図鑑',exact:true}).click();
 const stats=page.locator('.catalog-statistics');
 await expect(stats.locator('dt').filter({hasText:'平均終局報酬'}).locator('..')).toContainText('不明');
 await expect(stats).toContainText('報酬算出可能 0 / 1参加');
});

