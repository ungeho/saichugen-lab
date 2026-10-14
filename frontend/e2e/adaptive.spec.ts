import {test,expect} from '@playwright/test';
test('適応3方式・独立参照・コスト・直接URL・停止を操作する',async({page,request})=>{
 const stamp=Date.now(),c={name:'adaptive-ui-'+stamp,deals:1,start_offset:700000+stamp%10000,turns:[11],max_positions:1,budgets:[16,32],models:['Random'],repeats:2,reference_worlds:16,final_worlds:16,historical_limit:0};
 await page.goto('/research/adaptive');const panel=page.getByRole('region',{name:'Adaptive Sampling & Independent Reference Lab'});
 await panel.getByLabel('Adaptive Plan JSON').fill(JSON.stringify(c));await panel.getByRole('button',{name:'適応実験を見積もる',exact:true}).click();await expect(panel).toContainText('derived_games_upper');
 await panel.getByRole('button',{name:'適応の条件を登録',exact:true}).click();await expect(panel.getByRole('status').first()).toContainText('Registered');const url=page.url();const id=new URL(url).searchParams.get('experiment')!;expect(id).toBeTruthy();
 await panel.getByRole('button',{name:'登録Hashで適応実験を開始',exact:true}).click();await expect(panel.getByRole('status').first()).toContainText('Completed',{timeout:30000});
 await expect(panel).toContainText('Uncertainty-Adaptive');await expect(panel).toContainText('Gap-Adaptive');await expect(panel.getByRole('img',{name:'適応方式の計算コストと独立評価報酬'})).toBeVisible();
 await panel.getByText('Policy Selection / Reference Selection / Final Evaluation',{exact:true}).click();await expect(panel).toContainText('reference');const download=page.waitForEvent('download');await panel.getByRole('button',{name:'適応JSONを保存',exact:true}).click();expect((await download).suggestedFilename()).toBe('adaptive-'+id+'.json');
 const before=await(await request.get('/api/adaptive/jobs/'+id)).json();const posts:string[]=[];page.on('request',r=>{if(r.method()==='POST')posts.push(r.url());});
 await page.reload();await expect(panel.getByRole('status').first()).toContainText('Completed');await expect(panel.getByLabel('Adaptive Plan JSON')).toHaveValue(new RegExp(String(c.start_offset)));expect(posts).toEqual([]);expect((await(await request.get('/api/adaptive/jobs/'+id)).json()).condition_hash).toBe(before.condition_hash);
 await page.setViewportSize({width:390,height:844});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
 const v=await(await request.post('/api/adaptive/jobs',{data:{...c,start_offset:c.start_offset+20000}})).json();await page.goto('/research/adaptive?experiment='+v.id);await expect(panel.getByRole('status').first()).toContainText('Registered');
 await page.goBack();await expect(panel.getByRole('status').first()).toContainText('Completed');await expect(page).toHaveURL(url);await page.goForward();await expect(panel.getByRole('status').first()).toContainText('Registered');await expect(page).toHaveURL(new RegExp(v.id));
 await panel.getByRole('button',{name:'適応実験を停止',exact:true}).click();await expect(panel.getByRole('status').first()).toContainText('Cancelled');
});
test('不正IDと別LabのIDで再実行せずエラーを表示する',async({page,request})=>{
 const r=await(await request.post('/api/reliability/jobs',{data:{start_offset:770000+Date.now()%10000,max_positions:1,budgets:[16],models:['Random'],repeats:2,evaluation_worlds:16}})).json();
 await page.goto('/research/adaptive?experiment='+r.id);await expect(page.getByRole('alert')).toContainText('保存実験を開けません');
 await page.goto('/research/adaptive?experiment=missing');await expect(page.getByRole('alert')).toContainText('404');
 await page.goto('/research/adaptive');await expect(page.getByRole('button',{name:'適応の条件を登録',exact:true})).toBeVisible();
});
