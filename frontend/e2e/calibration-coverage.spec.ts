import {test,expect} from '@playwright/test';

test('既存Labで校正範囲の棚卸しと合成保存測定を確認する',async({page,request})=>{
 const response=await request.post('/api/runtime-divergence/jobs',{data:{revision:'phase40',series:'D',warmups:0,repeats:1,start_offset:90000+Date.now()%10000,turns:[14],max_positions:1,deals:1,models:['Random','Heuristic','ScoreAware'],budgets:[128]}});expect(response.ok()).toBeTruthy();const v=await response.json();
 await page.goto('/research/runtime-divergence?experiment='+v.id);await page.getByText('Calibration Coverage：測定条件と予測の適用範囲',{exact:true}).click();const area=page.locator('details').filter({has:page.getByText('Calibration Coverage：測定条件と予測の適用範囲',{exact:true})});
 await page.getByLabel('棚卸し・v2校正元ID').fill(v.id);await area.getByRole('button',{name:'校正データを棚卸し',exact:true}).click();await expect(area).toContainText('quality_counts');await expect(area).toContainText('Unknown');
 await area.getByRole('button',{name:'合成DBの保存負荷を測定',exact:true}).click();await expect(area).toContainText('calibration_storage_benchmark_v1',{timeout:30000});await expect(area).toContainText('transactions');
 await page.getByLabel('棚卸し・v2校正元ID').fill('non-existent-id');await area.getByRole('button',{name:'校正データを棚卸し',exact:true}).click();await expect(area.getByRole('alert')).toBeVisible();
 await page.setViewportSize({width:390,height:844});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
});
