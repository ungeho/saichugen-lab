import {test,expect} from '@playwright/test';

test('人間選択・全15ターン・公開履歴',async({page})=>{
 await page.goto('/');
 await page.getByRole('button',{name:'新しいゲーム'}).click();
 await expect(page.locator('.hand button')).toHaveCount(17);
 await page.locator('.hand button').first().click();
 await expect(page.locator('.hand button')).toHaveCount(16);
 for(let turn=1;turn<15;turn++){
  await page.getByRole('button',{name:'AIで1ターン進む'}).click();
  await expect(page.locator('.hand button')).toHaveCount(16-turn);
 }
 await expect(page.locator('.footnote').first()).toContainText('勝者');
 await expect(page.locator('.turns button')).toHaveCount(15);
 await expect(page.getByRole('button',{name:'AIで1ターン進む'})).toBeDisabled();
 await page.locator('.turns button').first().click();
 await expect(page.locator('.felt-label')).toHaveText('公開ターン 1');
 await page.screenshot({path:'test-results/game-desktop.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});
 await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
 await page.screenshot({path:'test-results/game-mobile.png',fullPage:true});
});

test('共通配札の比較実験とグラフ',async({page})=>{
 await page.goto('/');
 await page.getByRole('button',{name:'比較実験',exact:true}).click();
 await page.getByLabel('独立配札数').fill('3');
 await page.getByRole('button',{name:'比較実験を実行'}).click();
 await expect(page.locator('.metrics .panel')).toHaveCount(3);
 await expect(page.getByText('18 試合', {exact:false})).toBeVisible();
 await expect(page.locator('.chart canvas')).toHaveCount(4);
 await page.screenshot({path:'test-results/experiments-desktop.png',fullPage:true});
});
