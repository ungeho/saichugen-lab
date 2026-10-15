"""本番ExperimentStoreに触れない、有限の隔離WALベンチマーク。"""
from itertools import product
from pathlib import Path
from random import Random
from time import perf_counter,process_time,sleep
import json,os,sqlite3,subprocess,sys,tempfile
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator
from .evolution import digest


class StorageSpec(BaseModel):
    model_config=ConfigDict(extra='forbid')
    payload_seed:str=Field(default='44001',pattern=r'^[0-9]{1,20}$')
    order_seed:str=Field(default='44002',pattern=r'^[0-9]{1,20}$')
    checkpoints:int=Field(default=12,strict=True,ge=8,le=16)
    sizes:list[int]=Field(default=[512,4096,32768],min_length=3,max_length=3)
    frequencies:list[int]=Field(default=[1,4,12],min_length=3,max_length=3)
    batches:list[int]=Field(default=[1,4,12],min_length=3,max_length=3)
    warmups:Literal[1]=1
    repeats:int=Field(default=2,strict=True,ge=2,le=3)
    db_limit_bytes:int=Field(default=4194304,strict=True,ge=1048576,le=8388608)
    total_limit_bytes:int=Field(default=67108864,strict=True,ge=8388608,le=134217728)
    crash_after:int=Field(default=7,strict=True,ge=1,le=15)
    faults:bool=Field(default=True,strict=True)

    @model_validator(mode='after')
    def valid(self):
        if any(int(s)>2**64-1 for s in (self.payload_seed,self.order_seed)):raise ValueError('seedはuint64の十進文字列')
        if self.sizes!=sorted(set(self.sizes)) or any(type(s) is not int or not 256<=s<=65536 for s in self.sizes):raise ValueError('小/中/大の有限payloadサイズ')
        if self.frequencies!=[1,4,self.checkpoints] or self.batches!=[1,4,self.checkpoints]:raise ValueError('毎回/4回/完了時、1行/4行/全行の比較を固定')
        if self.crash_after>=self.checkpoints:raise ValueError('障害点は完了前')
        return self


def evidence(spec):
    rng=Random(int(spec.payload_seed))
    return [{'index':i,'schema':'synthetic-storage-evidence-v1','seed':spec.payload_seed,'value':rng.randrange(1000000)} for i in range(spec.checkpoints)]


def encode(logical,size):
    result=[]
    for row in logical:
        base={'evidence':row,'padding':''};n=len(json.dumps(base,ensure_ascii=False,separators=(',',':')).encode())
        base['padding']='x'*max(0,size-n);result.append(json.dumps(base,ensure_ascii=False,separators=(',',':')))
    return result


def open_db(path):
    db=sqlite3.connect(path,isolation_level=None);db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA synchronous=FULL')
    db.execute('CREATE TABLE IF NOT EXISTS evidence (plan TEXT, idx INTEGER, payload TEXT, PRIMARY KEY(plan,idx))')
    return db


def file_sizes(path):return {'db_bytes':path.stat().st_size if path.exists() else 0,'wal_bytes':Path(str(path)+'-wal').stat().st_size if Path(str(path)+'-wal').exists() else 0}


def insert(db,plan,rows):
    for i,text in rows:
        db.execute('INSERT OR IGNORE INTO evidence VALUES (?,?,?)',(plan,i,text))
        if db.execute('SELECT payload FROM evidence WHERE plan=? AND idx=?',(plan,i)).fetchone()[0]!=text:raise ValueError('同じキーの内容不一致')


def write(db,plan,payloads,frequency,batch,check=lambda:None):
    commits=0;writes=0;byte_count=0;seconds=0.;pending=[]
    for i,text in enumerate(payloads):
        check();pending.append((i,text))
        if (i+1)%frequency and i+1!=len(payloads):continue
        for start in range(0,len(pending),batch):
            check();chunk=pending[start:start+batch];t=perf_counter();db.execute('BEGIN IMMEDIATE')
            try:insert(db,plan,chunk);db.execute('COMMIT')
            except BaseException:db.execute('ROLLBACK');raise
            seconds+=perf_counter()-t;commits+=1;writes+=len(chunk);byte_count+=sum(len(x.encode()) for _,x in chunk)
        pending=[]
    return commits,writes,byte_count,seconds


def case(path,plan,logical,payloads,frequency,batch,check,limit):
    wall=perf_counter();cpu=process_time();db=open_db(path)
    try:
        def bounded():
            check()
            if sum(file_sizes(path).values())>limit:raise InterruptedError('SizeLimitExceeded')
        commits,writes,byte_count,write_wall=write(db,plan,payloads,frequency,batch,bounded)
        bounded();t=perf_counter();rows=[json.loads(x[0]) for x in db.execute('SELECT payload FROM evidence WHERE plan=? ORDER BY idx',(plan,))];read_wall=perf_counter()-t
        t=perf_counter();restored=[r['evidence'] for r in rows];actual=digest(restored);full=digest(rows);aggregate_wall=perf_counter()-t
        if actual!=digest(logical) or full!=digest([json.loads(x) for x in payloads]):raise ValueError('Evidence復元Hash不一致')
        integrity=db.execute('PRAGMA integrity_check').fetchone()[0];sizes=file_sizes(path)
    finally:db.close()
    return {'frequency':frequency,'batch':batch,'payload_bytes':[len(x.encode()) for x in payloads],'logical_bytes':byte_count,'write_count':writes,'commit_count':commits,
        'write_wall_seconds':write_wall,'read_wall_seconds':read_wall,'aggregate_wall_seconds':aggregate_wall,'wall_seconds':perf_counter()-wall,'cpu_seconds':process_time()-cpu,
        **sizes,'evidence_hash':actual,'payload_hash':full,'integrity':integrity,'plan_hash':plan,
        'durability':'各flush内をbatch単位でcommit。生成済みで未flush/未commitの行は障害時に失われ得る。',
        'byte_scope':'logical_bytesは投入JSONバイト合計。物理ディスク書込量ではない。WALサイズは接続close前。schema作成commitはdata commit回数外。'}


def crash_child(request_path):
    data=json.loads(Path(request_path).read_text());root=Path(data['root']).resolve();path=Path(data['path']).resolve()
    if not path.is_relative_to(root) or path.parent!=root or Path(data['state']).resolve().parent!=root:raise ValueError('隔離DBのみ')
    db=open_db(path);pending=[];committed=[]
    for i,text in enumerate(data['payloads'][:data['crash_after']]):
        pending.append((i,text))
        if (i+1)%data['frequency']==0:
            for start in range(0,len(pending),data['batch']):
                chunk=pending[start:start+data['batch']];db.execute('BEGIN IMMEDIATE');insert(db,data['plan'],chunk);db.execute('COMMIT');committed.extend(j for j,_ in chunk)
            pending=[]
    db.execute('BEGIN IMMEDIATE');insert(db,data['plan'],pending)
    state={'committed':committed,'uncommitted':[i for i,_ in pending],'plan_hash':data['plan']}
    with open(data['state'],'w',encoding='utf-8') as f:json.dump(state,f);f.flush();os.fsync(f.fileno())
    os._exit(17) # この子プロセス・隔離DBだけ。close/rollbackなしで終了する。


def fault(root,plan,logical,payloads,frequency,batch,after,check):
    path=root/('fault-'+str(frequency)+'.sqlite');state=root/('fault-'+str(frequency)+'.state.json');request=root/('fault-'+str(frequency)+'.request.json')
    request.write_text(json.dumps({'root':str(root),'path':str(path),'state':str(state),'payloads':payloads,'frequency':frequency,'batch':batch,'crash_after':after,'plan':plan}),encoding='utf-8')
    env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parents[2])+os.pathsep+os.environ.get('PYTHONPATH','')}
    process=subprocess.Popen([sys.executable,'-m','strategy_arena.experiments.storage_efficiency','--crash',str(request)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    started=perf_counter()
    try:
        while process.poll() is None:
            check()
            if perf_counter()-started>20:raise InterruptedError('FaultTimedOut')
            sleep(.02)
        if process.returncode!=17:raise ValueError('隔離障害プロセスが期待どおり終了しません')
    finally:
        if process.poll() is None:process.terminate();process.wait(timeout=5)
        if process.stderr:process.stderr.close()
    saved=json.loads(state.read_text());sizes=file_sizes(path)
    if saved['plan_hash']!=plan:raise ValueError('障害状態とPlan Hash不一致')
    db=open_db(path)
    try:
        ids=[i for i, in db.execute('SELECT idx FROM evidence WHERE plan=? ORDER BY idx',(plan,))]
        if ids!=saved['committed']:raise ValueError('最後のcommitからの復元不一致')
        prefix=[json.loads(x[0])['evidence'] for x in db.execute('SELECT payload FROM evidence WHERE plan=? ORDER BY idx',(plan,))]
        if digest(prefix)!=digest([logical[i] for i in ids]):raise ValueError('commit済Evidence Hash不一致')
        integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
        write(db,plan,payloads,frequency,batch,check);write(db,plan,payloads,frequency,batch,check)
        rows=[json.loads(x[0])['evidence'] for x in db.execute('SELECT payload FROM evidence WHERE plan=? ORDER BY idx',(plan,))]
        if len(rows)!=len(logical) or digest(rows)!=digest(logical):raise ValueError('再開/重複排除後のHash不一致')
    finally:db.close()
    return {'frequency':frequency,'batch':batch,'crash_after':after,'committed_ids':ids,'uncommitted_lost_ids':saved['uncommitted'],
        'not_yet_generated':list(range(after,len(logical))),'committed_evidence_hash':digest(prefix),'evidence_hash_after_resume':digest(rows),'integrity':integrity,'plan_hash':plan,**sizes,'exit_code':17,'duplicates_after_retry':len(rows)-len(logical)}


def run_storage(spec,parent,plan,result,check=lambda:None,progress=lambda:None):
    parent=Path(parent).resolve();parent.mkdir(parents=True,exist_ok=True);root=Path(tempfile.mkdtemp(prefix='storage-',dir=parent)).resolve()
    if not root.is_relative_to(parent):raise ValueError('隔離配置を確認できません')
    logical=evidence(spec);result.update(root=str(root),synthetic=True,logical_evidence_hash=digest(logical),rows=[],faults=[],expected_cases=27*(spec.warmups+spec.repeats),plan_hash=plan)
    def bounded():
        check()
        if sum(p.stat().st_size for p in root.iterdir() if p.is_file())>spec.total_limit_bytes:raise InterruptedError('SizeLimitExceeded')
    for repeat in range(spec.warmups+spec.repeats):
        conditions=list(product(spec.sizes,spec.frequencies,spec.batches));Random(int(spec.order_seed)+repeat).shuffle(conditions)
        for ordinal,(size,frequency,batch) in enumerate(conditions):
            bounded();payloads=encode(logical,size);path=root/(str(repeat)+'-'+str(ordinal)+'.sqlite')
            row=case(path,plan,logical,payloads,frequency,batch,bounded,spec.db_limit_bytes);row.update(size_label=spec.sizes.index(size),phase='warmup' if repeat<spec.warmups else 'measured',repeat=repeat,order_index=ordinal)
            result['rows'].append(row);progress()
    if spec.faults:
        for frequency in spec.frequencies:
            bounded();result['faults'].append(fault(root,plan,logical,encode(logical,spec.sizes[1]),frequency,4,spec.crash_after,bounded));progress()
    bounded();result['total_file_bytes']=sum(p.stat().st_size for p in root.iterdir() if p.is_file());result['complete']=True


if __name__=='__main__':
    if len(sys.argv)!=3 or sys.argv[1]!='--crash':raise SystemExit('専用障害子プロセスのみ')
    crash_child(sys.argv[2])
