import {test,expect} from '@playwright/test';
test('4規則の固定選択・独立評価・参照リンク・JSONを確認する',async({page,request})=>{
 const stamp=Date.now();await page.goto('/');await page.getByRole('button',{name:'Middle-Position Decision Lab',exact:true}).click();
 const panel=page.getByRole('region',{name:'Middle-Position Decision Lab'});
 const config={name:'decision-ui-'+stamp,deals:1,start_offset:320000+stamp%20000,validation_offset:340000+stamp%20000,turns:[6,11,12],max_positions:4,controls:1,trials:2,evaluation_trials:10,timeout_seconds:60};
 await panel.getByLabel('Decision Plan JSON').fill(JSON.stringify(config));await panel.getByRole('button',{name:'意思決定実験を見積もる',exact:true}).click();await expect(panel).toContainText('evaluation_games_upper');
 await panel.getByRole('button',{name:'4規則の条件を登録',exact:true}).click();await expect(panel.getByRole('status').first()).toContainText('Registered');
 await panel.getByRole('button',{name:'登録Hashで意思決定実験を開始',exact:true}).click();await expect(panel.getByRole('status').first()).toContainText('Completed',{timeout:30000});
 await expect(panel.getByRole('heading',{name:'選択段階：同じ全合法手から4規則で選ぶ',exact:true})).toBeVisible();await expect(panel.getByRole('heading',{name:'独立評価：選択に使わなかった世界で再評価',exact:true})).toBeVisible();
 await expect(panel.getByRole('img',{name:'4規則の独立評価と中間維持',exact:true})).toBeVisible();await expect(panel).toContainText('Safety-Margin − Self-Middle');await expect(panel).toContainText('minimum_margin');
 await panel.getByRole('checkbox',{name:'Self-MiddleとTerminal-Valueの選択不一致だけ'}).check();await panel.getByRole('checkbox',{name:'Self-MiddleとTerminal-Valueの選択不一致だけ'}).uncheck();
 await panel.getByRole('combobox',{name:'得点配置',exact:true}).selectOption('tie');await expect(panel).toContainText('この条件に分析済み局面はありません');await panel.getByRole('combobox',{name:'得点配置',exact:true}).selectOption('strict_middle');
 const download=page.waitForEvent('download');await panel.getByRole('button',{name:'意思決定JSONを保存',exact:true}).click();expect((await download).suggestedFilename()).toContain('decision-');
 await panel.getByRole('button',{name:'意思決定結果をEvidenceへ参照',exact:true}).click();await expect(panel.getByRole('status').last()).toContainText('"aggregated": false');
 await panel.getByRole('button',{name:'意思決定結果から別条件Draftを作る',exact:true}).click();await expect(panel.getByRole('status').last()).toContainText('Draft');
 await page.setViewportSize({width:390,height:844});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
 const v=await(await request.post('/api/decision/jobs',{data:{...config,start_offset:config.start_offset+100,validation_offset:config.validation_offset+100}})).json();
 expect((await request.post('/api/decision/jobs/'+v.id+'/cancel',{data:{}})).status()).toBe(200);
 expect((await(await request.get('/api/decision/jobs/'+v.id+'/export')).json()).status).toBe('Cancelled');
});

test('意思決定APIのエラーを表示し対戦画面へ戻れる',async({page})=>{
 await page.route('**/api/decision/jobs',route=>route.fulfill({status:500,contentType:'application/json',body:JSON.stringify({detail:'decision-test-error'})}));
 await page.goto('/');await page.getByRole('button',{name:'Middle-Position Decision Lab',exact:true}).click();
 await expect(page.getByRole('region',{name:'Middle-Position Decision Lab'}).getByRole('alert')).toContainText('decision-test-error');
 await page.getByRole('button',{name:'対戦テーブル',exact:true}).click();await expect(page.getByRole('button',{name:'新しいゲーム',exact:true})).toBeVisible();
});
