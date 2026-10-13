import {useEffect,useRef} from 'react';
import * as echarts from 'echarts';
export function Chart({option,label}:{option:echarts.EChartsOption;label:string}) {
  const ref=useRef<HTMLDivElement>(null);
  useEffect(()=>{if(!ref.current)return;const chart=echarts.init(ref.current,'dark');chart.setOption({...option,backgroundColor:'transparent'});const observer=new ResizeObserver(()=>chart.resize());observer.observe(ref.current);return()=>{observer.disconnect();chart.dispose();};},[option]);
  return <div ref={ref} className="chart" role="img" aria-label={label}/>;
}
