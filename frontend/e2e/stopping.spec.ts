import {test,expect} from '@playwright/test';
test('停止トレースと配札単位の結果を保存しID付きURLで復元する',async({page,request})=>{
 const c={name:'stopping-ui',start_offset:1800000+Date.now()%10000,deals:1,max_positions:1,turns:[11],models:['Random'],budgets:[32]};
 await page.goto('/research/stopping');const panel=page.getByRole('region',{name:'Adaptive Stopping Validation Lab'});await panel.getByLabel('Adaptive Plan JSON').fill(JSON.stringify(c));
 await panel.getByRole('button',{name:'適応実験を見積もる',exact:true}).click();await expect(panel).toContainText('derived_games_upper');await panel.getByRole('button',{name:'適応の条件を登録',exact:true}).click();await expect(panel.getByRole('status').first()).toContainText('Registered');
 const url=page.url(),id=new URL(url).searchParams.get('experiment')!;
 await panel.getByRole('button',{name:'登録Hashで適応実験を開始',exact:true}).click();await expect(panel.getByRole('status').first()).toContainText('Completed',{timeout:30000});
 const result=page.getByRole('region',{name:'停止の独立検証結果'});await expect(result).toContainText('早期停止率');await expect(result).toContainText('Fixed');await expect(result.getByRole('img',{name:'継続モデル別の早期停止率'})).toBeVisible();
 await result.getByText('停止判定の全構成要素・余裕・最終状態',{exact:true}).click();await expect(result).toContainText('合法手');await expect(result).toContainText('completed_fixed_budget');
 const download=page.waitForEvent('download');await panel.getByRole('button',{name:'適応JSONを保存',exact:true}).click();const saved=await download;expect(saved.suggestedFilename()).toContain(id);let raw='';const stream=await saved.createReadStream();for await(const chunk of stream!)raw+=chunk.toString();expect(raw).toBe(await(await request.get('/api/stopping/jobs/'+id+'/export')).text());
 const before=await(await request.get('/api/stopping/jobs/'+id)).json();const posts:string[]=[];page.on('request',r=>{if(r.method()==='POST')posts.push(r.url());});
 await page.reload();await expect(panel.getByRole('status').first()).toContainText('Completed');await expect(panel.getByLabel('Adaptive Plan JSON')).toHaveValue(new RegExp(String(c.start_offset)));expect(posts).toEqual([]);
 await page.goto('/reference/rules');await page.goBack();await expect(page).toHaveURL(url);await expect(panel.getByRole('status').first()).toContainText('Completed');expect((await(await request.get('/api/stopping/jobs/'+id)).json()).condition_hash).toBe(before.condition_hash);
 await page.setViewportSize({width:390,height:844});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
});
test('停止規則変更を拒否し別LabのIDを開かない',async({page,request})=>{
 const c={start_offset:1850000+Date.now()%10000,deals:1,max_positions:1,turns:[11],models:['Random']};
 expect((await request.post('/api/stopping/jobs',{data:{...c,gap_threshold:.4}})).status()).toBe(422);
 const old=await(await request.post('/api/adaptive/jobs',{data:{...c,partition:'validation'}})).json();await page.goto('/research/stopping?experiment='+old.id);await expect(page.getByRole('alert')).toContainText('404');await page.goto('/research/stopping?experiment=missing');await expect(page.getByRole('alert')).toContainText('404');
});
