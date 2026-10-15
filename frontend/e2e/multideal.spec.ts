import {test,expect} from '@playwright/test';
test('固定Planと配札単位の時間報酬を既存URLで確認・再読込する',async({page,request})=>{
 const c={revision:'phase38',series:'D',warmups:1,repeats:1,start_offset:68000+Date.now()%10000,turns:[14],max_positions:1,deals:1,models:['Random','Heuristic','ScoreAware'],budgets:[128]};
 const response=await request.post('/api/runtime-divergence/jobs',{data:c});expect(response.ok()).toBeTruthy();const v=await response.json();
 await page.goto('/research/runtime-divergence?experiment='+v.id);const panel=page.getByRole('region',{name:'Runtime Noise & Decision Divergence Lab'});
 await expect(panel.getByRole('status').first()).toContainText('Registered');await expect(page.getByRole('region',{name:'事前登録型複数配札検証'})).toContainText('固定済み');
 expect((await(await request.get('/api/runtime-divergence/jobs/'+v.id)).json()).status).toBe('Registered');
 await panel.getByRole('button',{name:'登録Hashで適応実験を開始',exact:true}).click();await expect(panel.getByRole('status').first()).toContainText('Completed',{timeout:30000});
 const result=page.getByRole('region',{name:'事前登録型複数配札検証'});await expect(result).toContainText('対応実時間差');await expect(result).toContainText('対応終局報酬差');await expect(result).toContainText('主要・3モデル等重み');
 const exported=await(await request.get('/api/runtime-divergence/jobs/'+v.id+'/export')).json();expect(exported.snapshot.study_plan_hash).toBe(v.snapshot.study_plan_hash);
 expect(exported.runtime_measurements.every((r:{seed:unknown})=>typeof r.seed==='string')).toBeTruthy();
 await page.reload();await expect(result).toContainText('固定済み');await page.goto('/reference/rules');await page.goBack();await expect(result).toContainText('Paired Results');
 await page.setViewportSize({width:390,height:844});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
});
test('配札照合なしの検証登録を拒否する',async({request})=>{
 const r=await request.post('/api/runtime-divergence/jobs',{data:{revision:'phase38',series:'D',stage:'independent_validation',partition:'validation',start_offset:1960000,deals:6,max_positions:6,turns:[4,10,11,14],budgets:[128],models:['Random','Heuristic','ScoreAware'],repeats:1,warmups:0,max_derived_games:80000,timeout_seconds:250}});expect(r.status()).toBe(422);
});
