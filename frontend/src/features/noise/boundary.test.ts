import {describe,it,expect} from 'vitest';
import {boundaryInitial,discoveryInitial,measurementInitial} from './BoundaryResults';
describe('Phase43の系列を分ける',()=>{
 it('Bは過去Evidence、Cは小規模開発、Mは別seedの反復計測',()=>{expect(discoveryInitial.boundary_series).toBe('B');expect(discoveryInitial.source_ids).toEqual([]);expect(boundaryInitial.boundary_series).toBe('C');expect(boundaryInitial.stage).toBe('development_pilot');expect(measurementInitial.start_offset).not.toBe(boundaryInitial.start_offset);expect(measurementInitial.max_positions).toBe(1);});
 it('停止と独立評価を固定し、凍結モデルは明示設定する',()=>{expect(boundaryInitial.budgets).toEqual([128]);expect(boundaryInitial.models).toEqual(['Random','Heuristic','ScoreAware']);expect(boundaryInitial.reference_worlds).toBe(16);expect(boundaryInitial.final_worlds).toBe(16);expect(boundaryInitial.calibration).toBeNull();});
});
