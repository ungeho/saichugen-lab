import {test,expect} from '@playwright/test';
test('ネスト予算・選択分布・モデル行列・独立評価を表示して保存する',async({page,request})=>{
 const stamp=Date.now();await page.goto('/');await page.getByRole('button',{name:'Decision Reliability Lab',exact:true}).click();
 const panel=page.getByRole('region',{name:'Decision Reliability Lab'});
 const c={name:'rel-ui-'+stamp,deals:1,start_offset:520000+stamp%20000,validation_offset:540000+stamp%20000,turns:[11,12],max_positions:1,budgets:[16,32],models:['Random','Heuristic','ScoreAware'],repeats:2,evaluation_worlds:16,historical_limit:0,timeout_seconds:60};
 await panel.getByLabel('Reliability Plan JSON').fill(JSON.stringify(c));await panel.getByRole('button',{name:'信頼性実験を見積もる',exact:true}).click();await expect(panel).toContainText('selection_games_upper');
 await panel.getByRole('button',{name:'信頼性の条件を登録',exact:true}).click();await expect(panel.getByRole('status').first()).toContainText('Registered');
 await panel.getByRole('button',{name:'登録Hashで信頼性実験を開始',exact:true}).click();await expect(panel.getByRole('status').first()).toContainText('Completed',{timeout:30000});
 await expect(panel.getByRole('img',{name:'予算別の選択推定と独立評価',exact:true})).toBeVisible();await expect(panel.getByRole('img',{name:'Terminal選択頻度',exact:true})).toBeVisible();
 await expect(panel.getByRole('heading',{name:'選択モデル × 評価モデル',exact:true})).toBeVisible();await expect(panel).toContainText('探索的Regret');await expect(panel).toContainText('自分の手札');
 await panel.getByRole('combobox',{name:'選択予算',exact:true}).selectOption('32');await panel.getByRole('combobox',{name:'選択モデル',exact:true}).selectOption('ScoreAware');await panel.getByRole('combobox',{name:'選択反復',exact:true}).selectOption('1');
 await panel.getByRole('combobox',{name:'診断と新規',exact:true}).selectOption('diagnostic');await expect(panel).toContainText('この条件に分析済み局面はありません');await panel.getByRole('combobox',{name:'診断と新規',exact:true}).selectOption('fresh');
 const download=page.waitForEvent('download');await panel.getByRole('button',{name:'信頼性JSONを保存',exact:true}).click();expect((await download).suggestedFilename()).toContain('reliability-');
 await panel.getByRole('button',{name:'信頼性結果をEvidenceへ参照',exact:true}).click();await expect(panel.getByRole('status').last()).toContainText('"aggregated": false');
 await panel.getByRole('button',{name:'信頼性結果から別条件Draftを作る',exact:true}).click();await expect(panel.getByRole('status').last()).toContainText('Draft');
 await page.setViewportSize({width:390,height:844});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
 const v=await(await request.post('/api/reliability/jobs',{data:{...c,start_offset:c.start_offset+100,validation_offset:c.validation_offset+100}})).json();
 expect((await request.post('/api/reliability/jobs/'+v.id+'/cancel',{data:{}})).status()).toBe(200);expect((await(await request.get('/api/reliability/jobs/'+v.id+'/export')).json()).status).toBe('Cancelled');
});
test('信頼性APIのエラーを表示し過去の対戦画面を維持する',async({page})=>{
 await page.route('**/api/reliability/jobs',route=>route.fulfill({status:500,contentType:'application/json',body:JSON.stringify({detail:'reliability-test-error'})}));
 await page.goto('/');await page.getByRole('button',{name:'Decision Reliability Lab',exact:true}).click();await expect(page.getByRole('region',{name:'Decision Reliability Lab'}).getByRole('alert')).toContainText('reliability-test-error');
 await page.getByRole('button',{name:'対戦テーブル',exact:true}).click();await expect(page.getByRole('button',{name:'新しいゲーム',exact:true})).toBeVisible();
});
