import {test,expect} from '@playwright/test';

test('候補生成と登録、親子評価、保留、提案JSONを分離する',async({page,request})=>{
 await page.goto('/');await page.getByRole('button',{name:'Strategy Evolution',exact:true}).click();
 const panel=page.getByRole('region',{name:'Strategy Evolution',exact:true});
 await expect(panel).toContainText('少数配札で自動採用しません');
 await panel.getByLabel('生成候補数').fill('1');
 // 既存版と衝突しないテスト専用patch。生成設定を入力に固定する。
 const patch=String(10000+Date.now()%900000);
 await panel.getByLabel('子版の最初のpatch').fill(patch);
 await panel.getByRole('button',{name:'候補JSONを生成（未登録）',exact:true}).click();
 await expect(panel.getByLabel('Evolution候補JSON')).toHaveValue(/definition_hash/);
 const candidate=JSON.parse(await panel.getByLabel('Evolution候補JSON').inputValue())[0];
 await panel.getByRole('button',{name:'候補を検証して登録',exact:true}).click();
 await panel.getByRole('checkbox').filter({hasText:''}).first().check();
 await panel.getByRole('button',{name:'評価計画JSONを作る',exact:true}).click();
 const editor=panel.getByLabel('Evolution評価計画JSON');await expect(editor).toHaveValue(/hypothesis/);
 const config=JSON.parse(await editor.inputValue());config.children=[candidate.id+'@'+candidate.version];config.deals=1;config.hypothesis='事前仮説：温存重みの変更';config.expected_effect='調整改善';config.side_effects='選択肢減少';
 await editor.fill(JSON.stringify(config));
 await panel.getByRole('button',{name:'計画を固定して保存（まだ対戦しない）',exact:true}).click();
 await expect(panel).toContainText('設定hash');
 await panel.getByRole('button',{name:'開発評価を開始',exact:true}).click();
 await expect(panel.getByRole('status')).toContainText('完了 · 12 / 12対局',{timeout:30000});
 await expect(panel).toContainText('開発評価済み');
 await panel.getByRole('button',{name:'検証評価を開始',exact:true}).click();
 await expect(panel.getByRole('status').last()).toContainText('完了 · 12 / 12対局',{timeout:30000});
 await expect(panel).toContainText('独立配札が採用基準未満');
 await expect(panel.getByRole('button',{name:'採用にする',exact:true})).toBeDisabled();
 const download=page.waitForEvent('download');await panel.getByRole('button',{name:'Codex改善提案用JSONを保存',exact:true}).click();
 expect((await download).suggestedFilename()).toBe('evolution-proposal.json');
 await panel.getByLabel('判定理由').fill('少数配札なので保留');
 await panel.getByRole('button',{name:'証拠不足・保留にする',exact:true}).click();
 await expect(panel).toContainText('証拠不足・保留');
 await page.setViewportSize({width:390,height:844});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
 const response=await request.get('/api/evolution/experiments');expect(response.ok()).toBe(true);
});
