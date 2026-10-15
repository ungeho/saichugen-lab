import {test,expect} from '@playwright/test';
test('同じLabで段階別費用・完了状態・校正モデル・固定予測を確認する',async({page,request})=>{
 const c={revision:'phase39',series:'D',warmups:0,repeats:1,start_offset:78000+Date.now()%10000,turns:[14],max_positions:1,deals:1,models:['Random','Heuristic','ScoreAware'],budgets:[128]};
 const response=await request.post('/api/runtime-divergence/jobs',{data:c});expect(response.ok()).toBeTruthy();const v=await response.json();
 await page.goto('/research/runtime-divergence?experiment='+v.id);const panel=page.getByRole('region',{name:'Runtime Noise & Decision Divergence Lab'});await expect(panel.getByRole('status').first()).toContainText('Registered');
 await panel.getByRole('button',{name:'登録Hashで適応実験を開始',exact:true}).click();await expect(panel.getByRole('status').first()).toContainText('Completed',{timeout:30000});
 const result=page.getByRole('region',{name:'予算校正と完了信頼性'});await expect(result).toContainText('完全評価 1 / 部分評価 0 / 未開始 0');await expect(result).toContainText('完了保証ではありません');await result.getByText('Cost Breakdown：排他的な処理時間と未計測残差',{exact:true}).click();await expect(result).toContainText('unmeasured_residual_seconds');
 const exported=await(await request.get('/api/runtime-divergence/jobs/'+v.id+'/export')).json();expect(exported.completion_audit.primary_finalized).toBeTruthy();expect(exported.cost_breakdown.overlap_or_timer_error).toBeFalsy();expect(exported.runtime_measurements.every((r:{seed:unknown})=>typeof r.seed==='string')).toBeTruthy();
 await page.getByText('Budget Calibration：保存実験から校正モデルを作る',{exact:true}).click();await page.getByLabel('校正元の実験ID',{exact:false}).fill(v.id);await page.getByRole('button',{name:'校正モデルを生成',exact:true}).click();await expect(page.locator('details').filter({has:page.getByText('Budget Calibration：保存実験から校正モデルを作る',{exact:true})})).toContainText('stage-turn-rate-v1');
 await page.reload();await expect(result).toContainText('完全評価 1');await page.goto('/reference/rules');await page.goBack();await expect(result).toContainText('完全評価 1');
 await page.setViewportSize({width:390,height:844});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
});
