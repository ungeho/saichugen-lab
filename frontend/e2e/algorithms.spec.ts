import {test,expect} from '@playwright/test';

test('戦略名から図鑑へ移動し、説明と実際の成績を確認する',async({page})=>{
 await page.goto('/');
 await page.getByRole('button',{name:'Greedyの説明',exact:true}).first().click();
 await expect(page.getByRole('dialog')).toBeVisible();
 await expect(page.getByRole('dialog')).toContainText('今のターンを、とにかく取りにいく');
 await page.getByRole('button',{name:'図鑑で詳しく見る'}).click();
 await expect(page.locator('.catalog-detail')).toContainText('カードを選ぶまで');
 await expect(page.locator('.catalog-detail')).toContainText('相手の2枚に挟まれて中位になる確率');
 await page.getByRole('button',{name:'比較実験',exact:true}).click();
 await page.getByLabel('独立配札数').fill('2');
 await page.getByRole('button',{name:'比較実験を実行'}).click();
 await expect(page.locator('.metrics .panel')).toHaveCount(3);
 await page.getByRole('button',{name:'アルゴリズム図鑑',exact:true}).click();
 await expect(page.locator('.stat-group').first()).toContainText('不完全情報');
 await expect(page.locator('.stat-group').first()).toContainText('参加回数');
 await page.screenshot({path:'test-results/catalog-desktop.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});
 await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
 await page.screenshot({path:'test-results/catalog-mobile.png',fullPage:true});
});

test('ランダムの評価なし、履歴の前後移動、終了後の全員分析',async({page})=>{
 await page.goto('/');
 await page.getByRole('button',{name:'新しいゲーム'}).click();
 await page.getByRole('button',{name:'AIで1ターン進む'}).click();
 const inspector=page.getByRole('region',{name:'判断過程の詳細'});
 await expect(inspector).toContainText('評価関数なし');
 await expect(inspector.locator('.candidate-table tbody tr')).toHaveCount(17);
 await expect(inspector.locator('.candidate-table tbody td').filter({hasText:'評価なし'})).toHaveCount(17);
 await inspector.getByRole('button',{name:'P2 Greedy',exact:true}).click();
 await expect(inspector).toContainText('対戦中は詳細を表示しません');
 for(let i=1;i<15;i++){
  await page.getByRole('button',{name:'AIで1ターン進む'}).click();
  await expect(page.locator('.hand button')).toHaveCount(16-i);
 }
 await inspector.getByRole('button',{name:'全員の判断を分析表示'}).click();
 await expect(inspector.getByRole('button',{name:'P2 Greedy',exact:true})).toHaveAttribute('aria-pressed','true');
 await expect(inspector.locator('.candidate-table tbody tr')).toHaveCount(3);
 await page.getByRole('button',{name:'前の判断',exact:true}).click();
 await expect(inspector).toContainText('ターン 14 の判断をたどる');
 await expect(inspector.locator('.candidate-table tbody tr')).toHaveCount(4);
 await expect(page.locator('.hand button')).toHaveCount(3);
 await page.getByRole('button',{name:'次の判断',exact:true}).click();
 await expect(inspector).toContainText('ターン 15 の判断をたどる');
 await inspector.getByRole('button',{name:'P3 Heuristic',exact:true}).click();
 await expect(inspector).toContainText('独自の加重評価');
 await inspector.locator('.candidate-table details').first().getByText('計算に使った値').click();
 await expect(inspector).toContainText('目標からの予想距離');
 await page.screenshot({path:'test-results/decision-desktop.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});
 await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
 await page.screenshot({path:'test-results/decision-mobile.png',fullPage:true});
});

test('詳細ログを無効にしても対戦できる',async({page})=>{
 await page.goto('/');
 await page.getByLabel('判断の詳細を記録（新しいゲームから適用）').uncheck();
 await page.getByRole('button',{name:'新しいゲーム'}).click();
 await page.getByRole('button',{name:'AIで1ターン進む'}).click();
 await expect(page.getByRole('region',{name:'判断過程の詳細'})).toContainText('詳細ログを記録していません');
 await expect(page.locator('.hand button')).toHaveCount(16);
});

test('図鑑の成績なしを表示し、データを作らない',async({page})=>{
 await page.route('**/api/algorithms/*/statistics',route=>route.fulfill({json:{name:'Random',groups:[],unclassified_experiments:0,note:'条件ごとに集計'}}));
 await page.goto('/');
 await page.getByRole('button',{name:'アルゴリズム図鑑',exact:true}).click();
 await expect(page.locator('.catalog-statistics')).toContainText('集計可能な保存結果はありません');
 await expect(page.locator('.stat-group')).toHaveCount(0);
});
