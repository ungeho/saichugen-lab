import {test,expect} from '@playwright/test';
test('分岐実験の結果・履歴・検証エラーを表示する',async({page})=>{
 await page.goto('/');
 await page.getByRole('button',{name:'新しいゲーム',exact:true}).click();
 await page.getByRole('button',{name:'AIで1ターン進む',exact:true}).click();
 await page.getByRole('button',{name:'同じ局面でAIを比較',exact:true}).click();
 const panel=page.getByRole('region',{name:'同一局面のアルゴリズム比較'});
 await panel.getByRole('combobox',{name:'比較する局面',exact:true}).selectOption('0');
 await panel.getByRole('button',{name:'この局面で比較する',exact:true}).click();
 const branch=page.getByRole('region',{name:'分岐シミュレーション',exact:true});
 await expect(branch.locator('input[type=checkbox]:checked')).not.toHaveCount(0);
 await branch.getByRole('spinbutton',{name:'分岐の試行回数',exact:true}).fill('3');
 await branch.getByRole('button',{name:'分岐シミュレーションを実行',exact:true}).click();
 await expect(branch.getByRole('status')).toContainText('計算完了');
 await expect(branch.locator('.branch-results')).toContainText('ターン 1');
 await expect(branch.getByRole('img',{name:'候補カード別の推定勝率'})).toBeVisible();
 await branch.getByText('サンプリングと再現条件', {exact:true}).click();
 await expect(branch.locator('.branch-results')).toContainText('uniform-unseen-v1');
 await branch.getByRole('spinbutton',{name:'分岐の試行回数',exact:true}).fill('0');
 await branch.getByRole('button',{name:'分岐シミュレーションを実行',exact:true}).click();
 await expect(branch.getByRole('alert')).toContainText('1〜1000');
 await page.setViewportSize({width:390,height:844});
 await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
});
test('分岐APIエラーを表示し対戦の操作を維持する',async({page})=>{
 await page.goto('/');
 await page.getByRole('button',{name:'新しいゲーム',exact:true}).click();
 await page.getByRole('button',{name:'同じ局面でAIを比較',exact:true}).click();
 const branch=page.getByRole('region',{name:'分岐シミュレーション',exact:true});
 await branch.locator('input[type=checkbox]').first().check();
 await page.route('**/api/games/*/branches',route=>route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({detail:'実験は1件ずつ実行してください'})}));
 await branch.getByRole('button',{name:'分岐シミュレーションを実行',exact:true}).click();
 await expect(branch.getByRole('alert')).toContainText('実験は1件ずつ');
 await page.getByRole('button',{name:'AIで1ターン進む',exact:true}).click();
 await expect(page.locator('.hand button')).toHaveCount(16);
});
test('計算中の進捗と停止を表示する',async({page})=>{
 await page.goto('/');
 await page.getByRole('button',{name:'新しいゲーム',exact:true}).click();
 await page.getByRole('button',{name:'同じ局面でAIを比較',exact:true}).click();
 const branch=page.getByRole('region',{name:'分岐シミュレーション',exact:true});
 await branch.locator('input[type=checkbox]').first().check();
 const job={id:'mock',status:'running',completed_trials:2,total_trials:100,candidate_count:1,result:null,error:null};
 await page.route('**/api/games/*/branches',route=>route.fulfill({status:202,json:job}));
 await page.route('**/api/branches/mock',route=>route.fulfill({json:job}));
 await page.route('**/api/branches/mock/cancel',route=>route.fulfill({json:{...job,status:'cancelled'}}));
 await branch.getByRole('button',{name:'分岐シミュレーションを実行',exact:true}).click();
 await expect(branch.getByRole('status')).toContainText('2 / 100');
 await branch.getByRole('button',{name:'計算を停止',exact:true}).click();
 await expect(branch.getByRole('status')).toContainText('停止しました');
});


