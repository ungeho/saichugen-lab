import {test,expect} from '@playwright/test';

test('現在局面で5戦略を比較し、対戦を変更せず選択の一致と内訳を見る',async({page,request})=>{
 await page.goto('/');
 const createdResponse=page.waitForResponse(response=>response.url().endsWith('/api/games')&&response.request().method()==='POST');
 await page.getByRole('button',{name:'新しいゲーム',exact:true}).click();
 const created=await (await createdResponse).json();
 await page.getByRole('button',{name:'同じ局面でAIを比較',exact:true}).click();
 const panel=page.getByRole('region',{name:'同一局面のアルゴリズム比較'});
 await expect(panel.locator('.position-hand .legal-card')).toHaveCount(17);
 const before=await (await request.get(`/api/games/${created.id}`)).json();
 const comparisonResponse=page.waitForResponse(response=>response.url().endsWith('/compare'));
 await panel.getByRole('button',{name:'この局面で比較する'}).click();
 const first=await (await comparisonResponse).json();
 await expect(panel.locator('.compared-strategy')).toHaveCount(5);
 const distinct=new Set(first.results.map((row:{decision:{card:{rank:number;suit:number}}})=>`${row.decision.card.rank}:${row.decision.card.suit}`));
 await expect(panel.locator('.choice-group')).toHaveCount(distinct.size);
 expect(await (await request.get(`/api/games/${created.id}`)).json()).toEqual(before);
 await panel.getByRole('button',{name:'Greedyの説明',exact:true}).click();
 await expect(page.getByRole('dialog')).toContainText('今のターンを、とにかく取りにいく');
 await page.getByRole('button',{name:'閉じる',exact:true}).click();
 const greedy=panel.getByRole('article',{name:'Greedyの比較結果',exact:true});
 await greedy.getByText('Greedyの候補評価・計算内訳を開く').click();
 await expect(greedy.locator('.candidate-table tbody tr')).toHaveCount(17);
 await greedy.getByText('Greedyの候補評価・計算内訳を開く').click();
 const random=panel.getByRole('article',{name:'Randomの比較結果',exact:true});
 await random.getByText('Randomの候補評価・計算内訳を開く').click();
 await expect(random).toContainText('評価関数なし');
 await expect(random.locator('.candidate-table tbody tr')).toHaveCount(17);
 await random.getByText('Randomの候補評価・計算内訳を開く').click();
 const repeatResponse=page.waitForResponse(response=>response.url().endsWith('/compare'));
 await panel.getByRole('button',{name:'この局面で比較する'}).click();
 const repeated=await (await repeatResponse).json();
 expect(repeated.results.map((row:{decision:unknown})=>row.decision)).toEqual(first.results.map((row:{decision:unknown})=>row.decision));
 await panel.getByRole('checkbox',{name:'Conservative v1',exact:true}).uncheck();
 await panel.getByRole('button',{name:'この局面で比較する'}).click();
 await expect(panel.locator('.compared-strategy')).toHaveCount(4);
 await panel.screenshot({path:'test-results/comparison-desktop.png'});
 await page.setViewportSize({width:390,height:844});
 await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
 await panel.screenshot({path:'test-results/comparison-mobile.png'});
 await page.getByRole('button',{name:'AIで1ターン進む',exact:true}).click();
 await expect(page.locator('.hand button')).toHaveCount(16);
 await expect(panel.locator('.compared-strategy')).toHaveCount(0);
 await expect(panel.locator('.position-heading')).toContainText('ターン 2 / 15');
});

test('履歴と連携して判断直前を比較し、未来の公開札を含めない',async({page,request})=>{
 await page.goto('/');
 const createdResponse=page.waitForResponse(response=>response.url().endsWith('/api/games')&&response.request().method()==='POST');
 await page.getByRole('button',{name:'新しいゲーム',exact:true}).click();
 const created=await (await createdResponse).json();
 for(let i=0;i<3;i++){
  await page.getByRole('button',{name:'AIで1ターン進む',exact:true}).click();
  await expect(page.locator('.hand button')).toHaveCount(16-i);
 }
 const before=await (await request.get(`/api/games/${created.id}`)).json();
 await page.getByRole('button',{name:'同じ局面でAIを比較',exact:true}).click();
 const panel=page.getByRole('region',{name:'同一局面のアルゴリズム比較'});
 await expect(panel.locator('.position-heading')).toContainText('ターン 4 / 15');
 await panel.getByRole('combobox',{name:'比較する局面',exact:true}).selectOption('1');
 await expect(panel.locator('.position-heading')).toContainText('ターン 2 / 15');
 await expect(panel.locator('.position-hand .card')).toHaveCount(16);
 await expect(panel.getByText('この局面までの公開済みカード（3枚）')).toBeVisible();
 const response=page.waitForResponse(r=>r.url().endsWith('/compare'));
 await panel.getByRole('button',{name:'この局面で比較する'}).click();
 const result=await (await response).json();
 expect(result.position.observation.turn).toBe(1);
 expect(result.position.observation.history).toHaveLength(1);
 await expect(panel).toContainText('当時の状態を復元');
 expect(await (await request.get(`/api/games/${created.id}`)).json()).toEqual(before);
 await page.getByRole('button',{name:'前の判断',exact:true}).click();
 await expect(panel.locator('.position-heading')).toContainText('ターン 1 / 15');
 await expect(panel.locator('.compared-strategy')).toHaveCount(0);
 await page.getByRole('button',{name:'最新に戻る',exact:true}).click();
 await expect(panel.locator('.position-heading')).toContainText('ターン 4 / 15');
});

test('終了後の視点比較でも、戦略には対象者自身の不完全情報を渡す',async({page})=>{
 await page.goto('/');
 await page.getByRole('button',{name:'新しいゲーム',exact:true}).click();
 for(let i=0;i<15;i++){
  await page.getByRole('button',{name:'AIで1ターン進む',exact:true}).click();
  await expect(page.locator('.hand button')).toHaveCount(16-i);
 }
 await page.getByRole('button',{name:'同じ局面でAIを比較',exact:true}).click();
 const panel=page.getByRole('region',{name:'同一局面のアルゴリズム比較'});
 await expect(panel.locator('.position-heading')).toContainText('ターン 15 / 15');
 await panel.getByRole('button',{name:'他プレイヤー視点を開く'}).click();
 await panel.getByRole('combobox',{name:'対象プレイヤー',exact:true}).selectOption('1');
 await expect(panel.locator('.position-heading')).toContainText('P2の選択直前');
 const response=page.waitForResponse(r=>r.url().endsWith('/compare'));
 await panel.getByRole('button',{name:'この局面で比較する'}).click();
 const result=await (await response).json();
 expect(result.position.information_condition).toBe('imperfect');
 expect(result.position.observation.player).toBe(1);
 expect(result.position.observation.hand).toHaveLength(3);
 expect(result.results.every((row:{status:string})=>row.status==='ok')).toBeTruthy();
 await expect(panel.locator('.compared-strategy')).toHaveCount(5);
});

test('比較の応答待ちに対戦を進めても、古い結果を新しい局面に表示しない',async({page})=>{
 await page.goto('/');
 await page.getByRole('button',{name:'新しいゲーム',exact:true}).click();
 await page.getByRole('button',{name:'同じ局面でAIを比較',exact:true}).click();
 const panel=page.getByRole('region',{name:'同一局面のアルゴリズム比較'});
 let release:()=>void=()=>{};let fetched:()=>void=()=>{};
 const hold=new Promise<void>(resolve=>{release=resolve;});
 const ready=new Promise<void>(resolve=>{fetched=resolve;});
 await page.route('**/compare',async route=>{const response=await route.fetch();fetched();await hold;await route.fulfill({response});});
 await panel.getByRole('button',{name:'この局面で比較する'}).click();
 await ready;
 await page.getByRole('button',{name:'AIで1ターン進む',exact:true}).click();
 await expect(panel.locator('.position-heading')).toContainText('ターン 2 / 15');
 const lateResponse=page.waitForResponse(r=>r.url().endsWith('/compare'));
 release();await lateResponse;
 await expect(panel.locator('.compared-strategy')).toHaveCount(0);
 await expect(page.locator('.hand button')).toHaveCount(16);
});
