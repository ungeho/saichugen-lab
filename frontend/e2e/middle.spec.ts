import {test,expect} from '@playwright/test';
test('Middleの固定条件・候補比較・参照連携と停止を操作する',async({page,request})=>{
 test.setTimeout(60000);const stamp=Date.now();await page.goto('/');await page.getByRole('button',{name:'Middle-Position Control Lab',exact:true}).click();
 const panel=page.getByRole('region',{name:'Middle-Position Control Lab'});
 const config={name:'middle-ui-'+stamp,deals:1,start_offset:120000+stamp%20000,validation_offset:140000+stamp%20000,turns:[12],trials:4,validation_trials:10,max_validate:1,reproduce:true,reproduce_rollouts:1,timeout_seconds:30};
 await panel.getByLabel('Middle実験JSON').fill(JSON.stringify(config));await panel.getByRole('button',{name:'Middleを見積もる',exact:true}).click();await expect(panel).toContainText('search_derived_games');
 await panel.getByRole('button',{name:'Middle条件を事前登録',exact:true}).click();await expect(panel.getByRole('status').first()).toContainText('Registered');
 await panel.getByRole('button',{name:'登録HashでMiddleを実行',exact:true}).click();await expect(panel.getByRole('status').first()).toContainText('Completed',{timeout:30000});
 await expect(panel.getByRole('img',{name:'目先の中間と終局価値',exact:true})).toBeVisible();await expect(panel.getByRole('img',{name:'開始時の上下得点差と報酬',exact:true})).toBeVisible();await expect(panel).toContainText('適用対象外');await expect(panel).toContainText('自分の手札');
 const download=page.waitForEvent('download');await panel.getByRole('button',{name:'Middle JSONを保存',exact:true}).click();expect((await download).suggestedFilename()).toContain('middle-');
 await panel.getByRole('button',{name:'Evidenceへ参照だけ関連付ける',exact:true}).click();await expect(panel.getByRole('status').last()).toContainText('"aggregated": false',{timeout:15000});
 await panel.getByRole('button',{name:'別条件の継続戦略比較Draftを作る',exact:true}).click();await expect(panel.getByRole('status').last()).toContainText('Draft');
 await page.setViewportSize({width:390,height:844});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
 const registered=await(await request.post('/api/middle/jobs',{data:{...config,start_offset:config.start_offset+100,validation_offset:config.validation_offset+100}})).json();
 expect((await request.post('/api/middle/jobs/'+registered.id+'/cancel',{data:{}})).status()).toBe(200);
 expect((await(await request.get('/api/middle/jobs/'+registered.id)).json()).status).toBe('Cancelled');
});
