import {test,expect} from '@playwright/test';

test('Arenaの候補・計画・結果・人工局面・保存履歴を確認する',async({page})=>{
 await page.goto('/');await page.getByRole('button',{name:'Strategy Arena',exact:true}).click();
 const arena=page.getByRole('region',{name:'Codex Strategy Arena',exact:true});
 await expect(arena).toContainText('すべて未検証');await expect(arena).toContainText('定義hash');
 await arena.getByLabel('Arena独立配札数').fill('1');
 await arena.getByRole('button',{name:'Arenaの規模を見積もる',exact:true}).click();
 await expect(arena).toContainText('予定 30対局');
 await arena.getByRole('button',{name:'このArena計画で実行',exact:true}).click();
 await expect(arena.getByRole('heading',{name:'Arenaの結果',exact:true})).toBeVisible();
 await expect(arena).toContainText('完了 · 30対局');
 await expect(arena.locator('tbody tr').first()).toContainText('codex_');
 await expect(arena).toContainText('10件未満');
 await arena.getByText('同一の公開人工局面での判断の違い',{exact:true}).click();
 await expect(arena).toContainText('公開固定seed42');
 await arena.getByText('相手構成・席順別の成績',{exact:true}).click();
 await expect(arena).toContainText('P1: 2対局');
 const download=page.waitForEvent('download');
 await arena.getByRole('button',{name:'Arena結果JSONを保存',exact:true}).click();
 expect((await download).suggestedFilename()).toMatch(/^arena-.*\.json$/);
 await page.screenshot({path:'test-results/strategy-arena-desktop.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});
 await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
 await page.screenshot({path:'test-results/strategy-arena-mobile.png',fullPage:true});
 await page.getByRole('button',{name:'ゲームルール',exact:true}).click();
 await page.getByRole('button',{name:'Strategy Arena',exact:true}).click();
 await expect(arena.getByLabel('Arenaの保存履歴').locator('option')).not.toHaveCount(1);
});

test('Arenaは任意コードを含む定義の登録と未許可探索を拒否する',async({page})=>{
 await page.goto('/');await page.getByRole('button',{name:'Strategy Arena',exact:true}).click();
 const arena=page.getByRole('region',{name:'Codex Strategy Arena',exact:true});
 await arena.getByText('新しい宣言戦略・版を登録',{exact:true}).click();
 await arena.getByLabel('宣言戦略JSON').fill(JSON.stringify({python:'print(1)'}));
 await arena.getByRole('button',{name:'検証して新しい版を登録',exact:true}).click();
 await expect(arena.getByRole('alert')).toBeVisible();
 await arena.getByLabel('Arena相手 1').selectOption('monte_carlo_rollout');
 await arena.getByRole('button',{name:'Arenaの規模を見積もる',exact:true}).click();
 await expect(arena.getByRole('alert')).toContainText('高コスト');
 await expect(arena.getByRole('button',{name:'このArena計画で実行',exact:true})).toBeDisabled();
});
