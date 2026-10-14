import {test,expect} from '@playwright/test';
test('予算上限の再構成結果・実コスト・原文JSON・URLを表示する',async({page,request})=>{
 const c={name:'horizon-ui',start_offset:1740000+Date.now()%10000,deals:1,max_positions:1,turns:[13],models:['Random'],budgets:[16,32,64,128,256]};
 await page.goto('/research/stopping-horizon');const panel=page.getByRole('region',{name:'Stopping Generalization & Budget Horizon Lab'});await panel.getByLabel('Adaptive Plan JSON').fill(JSON.stringify(c));
 await panel.getByRole('button',{name:'適応実験を見積もる',exact:true}).click();await expect(panel).toContainText('derived_games_upper');await panel.getByRole('button',{name:'適応の条件を登録',exact:true}).click();await expect(panel.getByRole('status').first()).toContainText('Registered');
 const url=page.url(),id=new URL(url).searchParams.get('experiment')!;await panel.getByRole('button',{name:'登録Hashで適応実験を開始',exact:true}).click();await expect(panel.getByRole('status').first()).toContainText('Completed',{timeout:30000});
 const result=page.getByRole('region',{name:'予算上限の研究結果'});await expect(result).toContainText('counterfactual_policy_cost');await expect(result.getByRole('img',{name:'予算上限別の早期停止率'})).toBeVisible();await expect(result).toContainText('256 / Fixed');await expect(result).toContainText('独立配札 1');
 await result.getByText('候補評価・停止トレース・実戦相当コスト',{exact:true}).click();await expect(result).toContainText('"elapsed_seconds": null');
 const download=page.waitForEvent('download');await panel.getByRole('button',{name:'適応JSONを保存',exact:true}).click();const saved=await download;let raw='';for await(const chunk of (await saved.createReadStream())!)raw+=chunk.toString();expect(raw).toBe(await(await request.get('/api/stopping-horizon/jobs/'+id+'/export')).text());
 const posts:string[]=[];page.on('request',r=>{if(r.method()==='POST')posts.push(r.url());});await page.reload();await expect(panel.getByRole('status').first()).toContainText('Completed');await expect(panel.getByLabel('Adaptive Plan JSON')).toHaveValue(new RegExp(String(c.start_offset)));
 await page.goto('/reference/rules');await page.goBack();await expect(page).toHaveURL(url);await expect(panel.getByRole('status').first()).toContainText('Completed');await page.goForward();await expect(page).toHaveURL(/reference\/rules/);await page.goBack();await expect(panel.getByRole('status').first()).toContainText('Completed');expect(posts).toEqual([]);
 await page.setViewportSize({width:390,height:844});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
});
test('別LabのID・不正ID・既観測配札を拒否しGETで実行しない',async({page,request})=>{
 const c={start_offset:1760000+Date.now()%10000,deals:1,max_positions:1,turns:[13],models:['Random'],budgets:[16,32]};expect((await request.post('/api/stopping-horizon/jobs',{data:{...c,start_offset:1900000}})).status()).toBe(422);
 const old=await(await request.post('/api/stopping/jobs',{data:c})).json();await page.goto('/research/stopping-horizon?experiment='+old.id);await expect(page.getByRole('alert')).toContainText('404');
 const posts:string[]=[];page.on('request',r=>{if(r.method()==='POST')posts.push(r.url());});await page.goto('/research/stopping-horizon?experiment=missing');await expect(page.getByRole('alert')).toContainText('404');expect(posts).toEqual([]);
});
