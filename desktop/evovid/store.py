"""SQLite 本地任务与事件日志。每次连接独立，避免线程跨连接复用。"""
from pathlib import Path
import sqlite3, json, time, uuid, threading
class Store:
    """保存任务状态；工作进程异常退出后，只标记中断，不假装已经恢复。"""
    def __init__(self, home: Path):
        self.home=Path(home); self.home.mkdir(parents=True, exist_ok=True)
        self.db=self.home/'tasks.sqlite3'; self.lock=threading.RLock()
        with self.connect() as c:
            c.executescript("""CREATE TABLE IF NOT EXISTS jobs
            (id TEXT PRIMARY KEY, created REAL, updated REAL, status TEXT,
             request TEXT, result TEXT, error TEXT);
            CREATE TABLE IF NOT EXISTS events
            (seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT, at REAL, kind TEXT, detail TEXT);""")
    def connect(self):
        """设置忙等待，数据库不会对外开放。"""
        c=sqlite3.connect(self.db,timeout=15); c.row_factory=sqlite3.Row;return c
    def create(self, request: dict):
        """生成服务端 UUID，不接受客户端路径。"""
        with self.lock, self.connect() as c:
            count=c.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]
            if count>=10: raise ValueError('Queue is full; maximum 10 outstanding jobs.')
            i=uuid.uuid4().hex;t=time.time()
            c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?)',(i,t,t,'queued',json.dumps(request,ensure_ascii=False),None,None))
        return i
    def get(self, job_id: str):
        """返回单任务副本。"""
        with self.connect() as c: r=c.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
        if not r: return None
        d=dict(r);d['request']=json.loads(d['request']);d['result']=json.loads(d['result']) if d['result'] else None
        return d
    def list(self):
        """按创建时间返回最近 100 个任务。"""
        with self.connect() as c: ids=[r[0] for r in c.execute('SELECT id FROM jobs ORDER BY created DESC LIMIT 100')]
        return [self.get(i) for i in ids]
    def update(self, job_id, status, result=None, error=None):
        """在事务中更新终态和结果。"""
        with self.lock,self.connect() as c:
            c.execute('UPDATE jobs SET updated=?,status=?,result=?,error=? WHERE id=?',
                (time.time(),status,json.dumps(result,ensure_ascii=False) if result is not None else None,error,job_id))
    def event(self,job_id,kind,detail):
        """日志只存结构化运行信息，不保存 API 密钥或完整模型 HTTP 响应。"""
        with self.lock,self.connect() as c:
            c.execute('INSERT INTO events(job_id,at,kind,detail) VALUES(?,?,?,?)',
                (job_id,time.time(),kind,json.dumps(detail,ensure_ascii=False)))
    def events(self,job_id):
        """获取可审查的执行轨迹。"""
        with self.connect() as c: rows=c.execute('SELECT * FROM events WHERE job_id=? ORDER BY seq',(job_id,)).fetchall()
        return [{**dict(r),'detail':json.loads(r['detail'])} for r in rows]
    def mark_interrupted(self):
        """重启后运行中的任务变为 interrupted，需显式继续。"""
        with self.lock,self.connect() as c:
            c.execute("UPDATE jobs SET status='interrupted',updated=? WHERE status='running'",(time.time(),))
