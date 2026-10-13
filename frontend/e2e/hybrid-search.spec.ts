import {test,expect} from '@playwright/test';

test('Hybridを対局・同一局面比較・図鑑・通常実験で使用できる',async({page})=>{
 await page.goto('/');
 await page.getByRole('combobox',{name:'プレイヤー 1',exact:true}).selectOption('hybrid_combined');
 await page.getByRole('button',{name:'新しいゲーム',exact:true}).click();
 await page.getByRole('button',{name:'AIで1ターン進む',exact:true}).click();
 const inspector=page.getByRole('region',{name:'判断過程の詳細'});
 const detail=inspector.getByRole('region',{name:'Hybrid探索の予算と配分'});
 await expect(detail).toContainText('総予算 64 / 開始 64 / 終局まで実行 64');
 await detail.getByText('候補別のRollout配分・補助指標',{exact:true}).click();
 await expect(detail.getByRole('img',{name:'候補カード別のRollout配分'})).toBeVisible();
 await page.getByRole('button',{name:'同じ局面でAIを比較',exact:true}).click();
 const comparison=page.getByRole('region',{name:'同一局面のアルゴリズム比較'});
 for(const name of ['budget_rollout','hybrid_heuristic','hybrid_adaptive','hybrid_combined']){
  await comparison.getByRole('checkbox',{name:new RegExp(name)}).check();
 }
 await comparison.getByRole('button',{name:'この局面で比較する',exact:true}).click();
 for(const name of ['budget_rollout','hybrid_heuristic','hybrid_adaptive','hybrid_combined'])
  await expect(comparison.getByRole('article',{name:name+'の比較結果'})).toBeVisible();
 await page.getByRole('button',{name:'比較実験',exact:true}).click();
 await page.getByLabel('独立配札数').fill('1');
 await page.getByRole('button',{name:'比較実験を実行',exact:true}).click();
 await expect(page.locator('.metrics')).toContainText('hybrid_combined');
 await page.getByRole('button',{name:'アルゴリズム図鑑',exact:true}).click();
 await page.getByRole('region',{name:'登録アルゴリズム'}).getByRole('button',{name:/hybrid_combined/}).click();
 await expect(page.locator('.catalog-detail')).toContainText('総予算');
 await expect(page.locator('.catalog-detail')).toContainText('Heuristic');
});

test('Hybrid Labの同一総予算実験と配分表示・不一致設定の拒否',async({page})=>{
 await page.goto('/');await page.getByRole('button',{name:'探索品質',exact:true}).click();
 const panel=page.getByRole('region',{name:'Rolloutの探索品質評価'});
 const editor=panel.getByLabel('探索品質実験の設定JSON');
 await expect(editor).toHaveValue(/"method": "uniform"/);
 const config=JSON.parse(await editor.inputValue());
 config.name='Hybrid UI 検証';
 for(const s of config.settings){s.total_budget=20;}
 await editor.fill(JSON.stringify(config));
 await panel.getByRole('button',{name:'実験規模を見積もる',exact:true}).click();
 await expect(panel.getByRole('status')).toContainText('予定 24対局');
 await panel.getByRole('button',{name:'この計画で実行',exact:true}).click();
 await expect(panel.getByRole('status').filter({hasText:'完了'})).toContainText('24 / 24');
 await expect(panel.locator('table').first().locator('tbody tr')).toHaveCount(4);
 await expect(panel.locator('table').first()).toContainText('Hybrid C 組み合わせ · 総予算20');
 await expect(panel.locator('table').first()).toContainText('10件未満のため区間を表示しません');
 await panel.getByText(/同じ局面で選択が/).first().click();
 await expect(panel).toContainText('方式ペア一致率');
 await expect(panel.getByRole('region',{name:'Hybrid探索の予算と配分'})).toHaveCount(4);
 config.settings[1].total_budget=32;
 await editor.fill(JSON.stringify(config));
 await panel.getByRole('button',{name:'実験規模を見積もる',exact:true}).click();
 await expect(panel.getByRole('alert')).toContainText('予算・最低試行');
 await page.setViewportSize({width:390,height:844});
 await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
});
