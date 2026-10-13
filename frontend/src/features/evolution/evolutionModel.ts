export const stateLabels:Record<string,string>={Candidate:'候補', 'Development Tested':'開発評価済み','Validation Passed':'検証基準を満たした',Promoted:'採用',Rejected:'棄却',Inconclusive:'証拠不足・保留'};
export const stageLabels:Record<string,string>={development:'開発評価',validation:'検証評価',final:'最終評価'};
export function canPromote(candidate:{evidence:Record<string,{passed:boolean}>}){
 return candidate.evidence.validation?.passed===true&&candidate.evidence.final?.passed===true;
}
