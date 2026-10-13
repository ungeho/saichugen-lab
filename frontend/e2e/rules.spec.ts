import {test,expect} from '@playwright/test';

test('ルールの確認状況・具体例・ナビゲーションと対戦の保持',async({page,request})=>{
 await page.goto('/');
 const creating=page.waitForResponse(r=>r.url().endsWith('/api/games')&&r.request().method()==='POST');
 await page.getByRole('button',{name:'新しいゲーム',exact:true}).click();
 const game=await (await creating).json();
 await page.getByRole('button',{name:'AIで1ターン進む',exact:true}).click();
 await page.getByRole('button',{name:'同じ局面でAIを比較',exact:true}).click();
 const before=await (await request.get('/api/games/'+game.id)).json();
 await page.getByRole('button',{name:'ゲームルール',exact:true}).click();
 const rules=page.getByRole('region',{name:'ゲームルール',exact:true});
 await expect(rules.getByRole('heading',{name:'カードは数字が先、同じ数字ならスート'})).toBeVisible();
 await expect(rules.locator('.rule-suits')).toContainText('スペード');
 expect(await rules.locator('.rule-suits>div span').allTextContents()).toEqual(['♠','♥','♦','♣']);
 await expect(rules).toContainText('二次資料に基づく暫定採用');
 await expect(rules).toContainText('実装上の暫定仕様');
 await expect(rules).toContainText('原典全文との一致は未確認');
 await expect(rules.locator('.rule-round-example').first()).toContainText('P1: 8 / P2: 8 / P3: 0');
 await rules.getByRole('heading',{name:'カードの強さ',exact:true}).locator('..').getByText('根拠と実装の対応',{exact:true}).click();
 await expect(rules.getByRole('link',{name:'サン・エム・システム「AIを身近に感じよう」'}).first()).toHaveAttribute('href','https://www.sun-m.co.jp/blog/latest-technology/147.html');
 expect(await (await request.get('/api/games/'+game.id)).json()).toEqual(before);
 await rules.screenshot({path:'test-results/rules-desktop.png'});
 await page.setViewportSize({width:390,height:844});
 await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
 await rules.screenshot({path:'test-results/rules-mobile.png'});
 await page.getByRole('button',{name:'対戦テーブル',exact:true}).click();
 await expect(page.locator('.hand button')).toHaveCount(16);
 await expect(page.getByRole('region',{name:'同一局面のアルゴリズム比較',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'比較実験',exact:true}).click();
 await page.getByRole('button',{name:'ゲームルール',exact:true}).click();
 await expect(rules.getByRole('heading',{name:'具体例で理解する'})).toBeVisible();
});

test('カード判定をエンジンで実行し、同一カードを拒否する',async({page})=>{
 await page.goto('/');
 await page.getByRole('button',{name:'ゲームルール',exact:true}).click();
 const rules=page.getByRole('region',{name:'ゲームルール',exact:true});
 await rules.getByRole('button',{name:'この3枚を判定',exact:true}).click();
 await expect(rules.locator('.rule-sample-result')).toContainText('P3の♥7が中間');
 await rules.getByRole('combobox',{name:'P1のスート',exact:true}).selectOption('1');
 await expect(rules.locator('.rule-sample-result')).toHaveCount(0);
 await rules.getByRole('button',{name:'この3枚を判定',exact:true}).click();
 await expect(rules.locator('.rule-sample-result')).toContainText('P1の♦7が中間');
 await rules.getByRole('combobox',{name:'P1のスート',exact:true}).selectOption('0');
 await rules.getByRole('button',{name:'この3枚を判定',exact:true}).click();
 await expect(rules.getByRole('alert')).toContainText('異なるカード3枚が必要');
 await expect(rules.locator('.rule-sample-result')).toHaveCount(0);
});

test('ルール取得エラーから再読み込みできる',async({page})=>{
 await page.goto('/');
 await page.route('**/api/rules',route=>route.fulfill({status:503,body:'ルール取得に失敗'}));
 await page.getByRole('button',{name:'ゲームルール',exact:true}).click();
 const rules=page.getByRole('region',{name:'ゲームルール',exact:true});
 await expect(rules.getByRole('alert')).toContainText('503');
 await page.unroute('**/api/rules');
 await rules.getByRole('button',{name:'ルールを再読み込み',exact:true}).click();
 await expect(rules.getByRole('heading',{name:'遊び方と確認状況'})).toBeVisible();
});

