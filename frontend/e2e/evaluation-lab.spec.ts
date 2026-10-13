import {test,expect} from '@playwright/test';

test('2配札で精密な必要数を出さず、複数相手のAblationと推薦を保存する',async({page})=>{
 await page.goto('/');await page.getByRole('button',{name:'Evaluation Lab',exact:true}).click();
 const panel=page.getByRole('region',{name:'Evaluation Lab',exact:true});
 await panel.getByRole('button',{name:'必要配札数を見積もる',exact:true}).click();
 await expect(panel.getByRole('status')).toContainText('予備評価が必要');
 await panel.getByRole('button',{name:'温存系Ablationを準備',exact:true}).click();
 await expect(panel.getByLabel('Evaluation計画JSON')).toHaveValue(/reserve_ablation/);
 const editor=panel.getByLabel('Evaluation計画JSON');const config=JSON.parse(await editor.inputValue());
 config.start_offset=10000+Date.now()%800000;await editor.fill(JSON.stringify(config));
 await panel.getByRole('button',{name:'Evaluation規模を見積もる',exact:true}).click();
 await expect(panel.getByRole('status').last()).toContainText('予定 96対局');
 await panel.getByRole('button',{name:'固定計画でEvaluationを実行',exact:true}).click();
 await expect(panel.getByRole('status').last()).toContainText('完了 · 96 / 96対局',{timeout:30000});
 await expect(panel.getByRole('heading',{name:/Ablation：/})).toHaveCount(2);
 await expect(panel).toContainText('独立配札10件未満');
 await expect(panel).toContainText('相互作用は11−10−01＋00');
 await expect(panel).toContainText('統合なし');
 await expect(panel.getByRole('heading',{name:'次の実験（決定的な規則による提案）',exact:true})).toBeVisible();
 const download=page.waitForEvent('download');await panel.getByRole('button',{name:'Evaluation結果JSONを保存',exact:true}).click();
 expect((await download).suggestedFilename()).toMatch(/^evaluation-.*\.json$/);
 const recommendations=panel.getByRole('heading',{name:'次の実験（決定的な規則による提案）',exact:true}).locator('..');
 await recommendations.locator('details').first().locator('summary').click();
 await recommendations.getByRole('button',{name:'推薦を計画欄へコピー（実行しない）',exact:true}).first().click();
 await expect(editor).toHaveValue(/次の開発パイロット/);
 await expect(panel.getByRole('button',{name:'固定計画でEvaluationを実行',exact:true})).toBeDisabled();
 await page.setViewportSize({width:390,height:844});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
});

test('逐次判定と最終seedの実行要求を拒否する',async({page})=>{
 await page.goto('/');await page.getByRole('button',{name:'Evaluation Lab',exact:true}).click();
 const panel=page.getByRole('region',{name:'Evaluation Lab',exact:true});const editor=panel.getByLabel('Evaluation計画JSON');
 const config=JSON.parse(await editor.inputValue());config.evaluation_mode='sequential';
 await editor.fill(JSON.stringify(config));await panel.getByRole('button',{name:'Evaluation規模を見積もる',exact:true}).click();
 await expect(panel.getByRole('alert')).toContainText('422');
 config.evaluation_mode='fixed';config.seed_partition='final';await editor.fill(JSON.stringify(config));
 await panel.getByRole('button',{name:'Evaluation規模を見積もる',exact:true}).click();
 await expect(panel.getByRole('alert')).toContainText('422');
 await expect(panel.getByRole('button',{name:'固定計画でEvaluationを実行',exact:true})).toBeDisabled();
});
