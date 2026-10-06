"""Durable plans, bounded queue, immutable evidence, and confirmed decisions.

Simulation is safe to recompute after a crash. Only one result can be committed
per task. External side effects need a separate idempotent adapter (M2).
"""
from contextlib import closing, contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid


class Conflict(ValueError):
    pass


class NotFound(ValueError):
    pass


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def text(value, name, maximum=4000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{name}需要 1–{maximum} 个字符")
    return value.strip()


def scenario(value):
    if value not in ("clean", "outlier"):
        raise ValueError("请选择平稳数据或含异常点数据")
    return value


def quota(value):
    if type(value) is not int or not 0 <= value <= 100:
        raise ValueError("模拟任务预算应为 0–100 的整数")
    return value


SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
 id TEXT PRIMARY KEY, title TEXT NOT NULL, idea TEXT NOT NULL,
 version INTEGER NOT NULL, scenario TEXT NOT NULL,
 budget INTEGER NOT NULL, used INTEGER NOT NULL DEFAULT 0,
 qa_budget INTEGER NOT NULL, qa_used INTEGER NOT NULL DEFAULT 0,
 paused INTEGER NOT NULL DEFAULT 0, meeting_at REAL, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
 version INTEGER NOT NULL, role TEXT NOT NULL, instruction TEXT NOT NULL,
 scenario TEXT NOT NULL, dependency TEXT REFERENCES tasks(id),
 status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
 charged INTEGER NOT NULL DEFAULT 0, owner TEXT, lease_until REAL,
 created REAL NOT NULL, finished REAL, error TEXT,
 UNIQUE(project_id,version,role)
);
CREATE TABLE IF NOT EXISTS artifacts (
 id TEXT PRIMARY KEY, task_id TEXT NOT NULL UNIQUE REFERENCES tasks(id),
 project_id TEXT NOT NULL REFERENCES projects(id), version INTEGER NOT NULL,
 role TEXT NOT NULL, body TEXT NOT NULL, sha256 TEXT NOT NULL, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS meetings (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
 version INTEGER NOT NULL, snapshot TEXT NOT NULL, status TEXT NOT NULL,
 created REAL NOT NULL, UNIQUE(project_id,version)
);
CREATE TABLE IF NOT EXISTS discussion (
 id TEXT PRIMARY KEY, meeting_id TEXT NOT NULL REFERENCES meetings(id),
 question TEXT NOT NULL, answer TEXT NOT NULL, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS decisions (
 id TEXT PRIMARY KEY, meeting_id TEXT NOT NULL UNIQUE REFERENCES meetings(id),
 project_id TEXT NOT NULL REFERENCES projects(id),
 from_version INTEGER NOT NULL, to_version INTEGER NOT NULL,
 instruction TEXT NOT NULL, scenario TEXT NOT NULL, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS meeting_drafts (
 meeting_id TEXT PRIMARY KEY REFERENCES meetings(id), instruction TEXT NOT NULL,
 scenario TEXT NOT NULL, revision INTEGER NOT NULL, edited REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
 kind TEXT NOT NULL, body TEXT NOT NULL, created REAL NOT NULL
);
CREATE TRIGGER IF NOT EXISTS artifact_no_update BEFORE UPDATE ON artifacts
 BEGIN SELECT RAISE(ABORT,'Evidence is immutable'); END;
CREATE TRIGGER IF NOT EXISTS artifact_no_delete BEFORE DELETE ON artifacts
 BEGIN SELECT RAISE(ABORT,'Evidence is immutable'); END;
CREATE TRIGGER IF NOT EXISTS snapshot_no_update BEFORE UPDATE OF snapshot ON meetings
 BEGIN SELECT RAISE(ABORT,'Meeting snapshots are immutable'); END;
"""


class Store:
    def __init__(self, database):
        self.database = Path(database).absolute()
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.database, timeout=10, isolation_level=None)) as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript(SCHEMA)

    @contextmanager
    def connection(self, write=False):
        con = sqlite3.connect(self.database, timeout=10, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        try:
            con.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    @staticmethod
    def row(con, table, identifier):
        # Table names are fixed by application callers, never request input.
        result = con.execute(f"SELECT * FROM {table} WHERE id=?", (identifier,)).fetchone()
        if result is None:
            raise NotFound("找不到这条记录")
        return dict(result)

    @staticmethod
    def event(con, project_id, kind, body):
        con.execute("INSERT INTO events(project_id,kind,body,created) VALUES(?,?,?,?)",
                    (project_id, kind, encode(body), time.time()))

    def add_round(self, con, project_id, version, direction, selected):
        previous = None
        for role in ("researcher", "executor", "reviewer"):
            identifier = uuid.uuid4().hex
            con.execute("INSERT INTO tasks(id,project_id,version,role,instruction,scenario,dependency,status,created) VALUES(?,?,?,?,?,?,?,?,?)",
                        (identifier, project_id, version, role, direction, selected, previous, "queued", time.time()))
            previous = identifier

    def create_project(self, title, idea, selected="clean", budget=9, qa_budget=6, meeting_at=None):
        title, idea = text(title, "项目名称", 120), text(idea, "研究想法")
        selected, budget, qa_budget = scenario(selected), quota(budget), quota(qa_budget)
        if meeting_at is not None and (type(meeting_at) not in (int, float) or not 0 < meeting_at < 4102444800):
            raise ValueError("组会时间无效")
        identifier = uuid.uuid4().hex
        with self.connection(write=True) as con:
            con.execute("INSERT INTO projects(id,title,idea,version,scenario,budget,qa_budget,meeting_at,created) VALUES(?,?,?,?,?,?,?,?,?)",
                        (identifier, title, idea, 1, selected, budget, qa_budget, meeting_at, time.time()))
            self.add_round(con, identifier, 1, idea, selected)
            self.event(con, identifier, "project_created", {"simulation": True})
        return identifier

    def projects(self):
        with self.connection() as con:
            return [dict(r) for r in con.execute("SELECT * FROM projects ORDER BY created DESC")]

    def project(self, identifier):
        with self.connection() as con:
            result = self.row(con, "projects", identifier)
            for table in ("tasks", "artifacts", "meetings", "decisions", "events"):
                result[table] = [dict(r) for r in con.execute(f"SELECT * FROM {table} WHERE project_id=? ORDER BY created", (identifier,))]
            for artifact in result["artifacts"]:
                artifact["body"] = json.loads(artifact["body"])
            for meeting in result["meetings"]:
                meeting["snapshot"] = json.loads(meeting["snapshot"])
            return result

    def configure(self, identifier, paused, budget, qa_budget, meeting_at=None):
        if type(paused) is not bool:
            raise ValueError("暂停状态必须为布尔值")
        budget, qa_budget = quota(budget), quota(qa_budget)
        if meeting_at is not None and (type(meeting_at) not in (int, float) or not 0 < meeting_at < 4102444800):
            raise ValueError("组会时间无效")
        with self.connection(write=True) as con:
            self.row(con, "projects", identifier)
            con.execute("UPDATE projects SET paused=?,budget=?,qa_budget=?,meeting_at=? WHERE id=?",
                        (paused, budget, qa_budget, meeting_at, identifier))
            self.event(con, identifier, "project_configured", {"paused": paused, "budget": budget, "qa_budget": qa_budget, "meeting_at": meeting_at})

    def claim(self, now=None, lease_seconds=30):
        now = time.time() if now is None else now
        with self.connection(write=True) as con:
            # Expired leases are fenced by a new owner; bounded simulation retries.
            expired = con.execute("SELECT * FROM tasks WHERE status='running' AND lease_until<=?", (now,)).fetchall()
            for old in expired:
                p = self.row(con, "projects", old["project_id"])
                new_status = "cancelled" if old["version"] != p["version"] else ("failed" if old["attempts"] >= 3 else "queued")
                con.execute("UPDATE tasks SET status=?,owner=NULL,lease_until=NULL,error=? WHERE id=?",
                            (new_status, "运行中断，租约过期；仅模拟任务可安全重算", old["id"]))
                self.event(con, p["id"], "lease_expired", {"task_id": old["id"], "status": new_status})
            rows = con.execute("""SELECT t.* FROM tasks t JOIN projects p ON p.id=t.project_id
                LEFT JOIN tasks d ON d.id=t.dependency
                WHERE t.status='queued' AND p.paused=0 AND t.version=p.version
                  AND (t.dependency IS NULL OR d.status='completed')
                  AND (t.charged=1 OR p.used<p.budget)
                ORDER BY t.created LIMIT 1""").fetchall()
            if not rows:
                return None
            task = dict(rows[0])
            owner = uuid.uuid4().hex
            if not task["charged"]:
                con.execute("UPDATE projects SET used=used+1 WHERE id=?", (task["project_id"],))
            con.execute("UPDATE tasks SET status='running',charged=1,attempts=attempts+1,owner=?,lease_until=?,error=NULL WHERE id=?",
                        (owner, now+lease_seconds, task["id"]))
            self.event(con, task["project_id"], "task_started", {"task_id": task["id"], "attempt": task["attempts"]+1})
            return self.row(con, "tasks", task["id"])

    def dependency_artifact(self, task):
        if not task["dependency"]:
            return None
        with self.connection() as con:
            row = con.execute("SELECT * FROM artifacts WHERE task_id=?", (task["dependency"],)).fetchone()
            if row is None:
                raise Conflict("前置证据缺失")
            result = dict(row)
            body = result["body"]
            if hashlib.sha256(body.encode()).hexdigest() != result["sha256"]:
                raise Conflict("前置证据哈希不一致")
            result["body"] = json.loads(body)
            return result

    def complete(self, task, body):
        canonical = encode(body)
        with self.connection(write=True) as con:
            current = self.row(con, "tasks", task["id"])
            if current["status"] != "running" or current["owner"] != task["owner"]:
                raise Conflict("任务租约已转移，旧 worker 的结果不能写入")
            if current["lease_until"] <= time.time():
                raise Conflict("任务租约已过期")
            con.execute("INSERT INTO artifacts(id,task_id,project_id,version,role,body,sha256,created) VALUES(?,?,?,?,?,?,?,?)",
                        (uuid.uuid4().hex, task["id"], task["project_id"], task["version"], task["role"], canonical, hashlib.sha256(canonical.encode()).hexdigest(), time.time()))
            con.execute("UPDATE tasks SET status='completed',finished=?,owner=NULL,lease_until=NULL WHERE id=?", (time.time(), task["id"]))
            self.event(con, task["project_id"], "task_completed", {"task_id": task["id"], "version": task["version"]})

    def fail(self, task, error):
        with self.connection(write=True) as con:
            current = self.row(con, "tasks", task["id"])
            if current["owner"] != task["owner"] or current["status"] != "running":
                return
            con.execute("UPDATE tasks SET status='failed',error=?,finished=?,owner=NULL,lease_until=NULL WHERE id=?",
                        (str(error)[:2000], time.time(), task["id"]))
            self.event(con, task["project_id"], "task_failed", {"task_id": task["id"], "error": str(error)[:2000]})

    def artifact(self, identifier):
        with self.connection() as con:
            result = self.row(con, "artifacts", identifier)
            if hashlib.sha256(result["body"].encode()).hexdigest() != result["sha256"]:
                raise Conflict("证据哈希不一致")
            return result

    def open_meeting(self, project_id):
        with self.connection(write=True) as con:
            return self._open_meeting(con, project_id)

    def _open_meeting(self, con, project_id):
        p = self.row(con, "projects", project_id)
        existing = con.execute("SELECT id FROM meetings WHERE project_id=? AND version=?", (project_id, p["version"])).fetchone()
        if existing:
            con.execute("UPDATE projects SET meeting_at=NULL WHERE id=?", (project_id,))
            return existing["id"]
        tasks = [dict(r) for r in con.execute("SELECT id,role,status,version,error FROM tasks WHERE project_id=? AND version=? ORDER BY created", (project_id, p["version"]))]
        artifacts = [dict(r) for r in con.execute("SELECT * FROM artifacts WHERE project_id=? AND version=? ORDER BY created", (project_id, p["version"]))]
        for a in artifacts:
            a["body"] = json.loads(a["body"])
        snapshot = {"simulation": True, "cutoff": time.time(), "idea": p["idea"], "scenario": p["scenario"], "tasks": tasks, "artifacts": artifacts,
                    "notice": "这是开会时的固定快照。之后完成的任务请在项目最新进度中查看。"}
        identifier = uuid.uuid4().hex
        con.execute("INSERT INTO meetings VALUES(?,?,?,?,?,?)", (identifier, project_id, p["version"], encode(snapshot), "in_review", time.time()))
        con.execute("UPDATE projects SET meeting_at=NULL WHERE id=?", (project_id,))
        self.event(con, project_id, "meeting_opened", {"meeting_id": identifier, "version": p["version"]})
        return identifier

    def due_meetings(self, now=None):
        now = time.time() if now is None else now
        with self.connection(write=True) as con:
            due = [r["id"] for r in con.execute("SELECT id FROM projects WHERE meeting_at<=?", (now,))]
            return [self._open_meeting(con, identifier) for identifier in due]

    def meeting(self, identifier):
        with self.connection() as con:
            result = self.row(con, "meetings", identifier)
            result["snapshot"] = json.loads(result["snapshot"])
            result["discussion"] = [dict(r) for r in con.execute("SELECT * FROM discussion WHERE meeting_id=? ORDER BY created", (identifier,))]
            decision = con.execute("SELECT * FROM decisions WHERE meeting_id=?", (identifier,)).fetchone()
            result["decision"] = dict(decision) if decision else None
            draft = con.execute("SELECT * FROM meeting_drafts WHERE meeting_id=?", (identifier,)).fetchone()
            result["draft"] = dict(draft) if draft else None
            return result

    def save_draft(self, meeting_id, expected_revision, instruction, selected):
        instruction, selected = text(instruction, "决策草稿"), scenario(selected)
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("草稿版本应为非负整数")
        with self.connection(write=True) as con:
            meeting = self.row(con, "meetings", meeting_id)
            if meeting["status"] == "closed":
                raise Conflict("已确认的决定不能再改为草稿")
            previous = con.execute("SELECT * FROM meeting_drafts WHERE meeting_id=?", (meeting_id,)).fetchone()
            revision = previous["revision"] if previous else 0
            if revision != expected_revision:
                raise Conflict("草稿已在其他页面更新，请刷新后核对")
            draft = {"meeting_id": meeting_id, "instruction": instruction, "scenario": selected,
                     "revision": revision+1, "edited": time.time()}
            con.execute("INSERT INTO meeting_drafts VALUES(:meeting_id,:instruction,:scenario,:revision,:edited) ON CONFLICT(meeting_id) DO UPDATE SET instruction=excluded.instruction,scenario=excluded.scenario,revision=excluded.revision,edited=excluded.edited", draft)
            self.event(con, meeting["project_id"], "draft_saved", draft)
            return draft

    def ask(self, meeting_id, question):
        question = text(question, "问题", 1000)
        with self.connection(write=True) as con:
            meeting = self.row(con, "meetings", meeting_id)
            if meeting["status"] == "closed":
                raise Conflict("这场组会已结束，请在新一轮组会追问")
            p = self.row(con, "projects", meeting["project_id"])
            if p["qa_used"] >= p["qa_budget"]:
                raise Conflict("组会模拟问答预算已用完；可在项目设置中增加")
            snapshot = json.loads(meeting["snapshot"])
            count = len(snapshot["artifacts"])
            by_role = {a["role"]: a for a in snapshot["artifacts"]}
            if any(word in question for word in ("预算", "费用", "停止")):
                detail = f"后台模拟任务已用 {p['used']}/{p['budget']}；本次答复后问答已用 {p['qa_used']+1}/{p['qa_budget']}。达到上限就停止启动对应任务。这些计数不是 API token 或费用。"
            elif any(word in question for word in ("复核", "核验", "可信", "证据", "验证")):
                review = by_role.get("reviewer")
                detail = review["body"]["summary"] if review else "快照中还没有复核产物，不能声称结果已经核验。"
                detail += "原始证据入口保存了输入、计算结果和逐项检查；没有检索论文。"
            else:
                computed = by_role.get("executor")
                detail = computed["body"]["summary"] if computed else "快照中还没有计算结果，需要先完成计算再讨论数值。"
                detail += "样本只有 5 个，还没有用新数据验证。"
            answer = f"【模拟模板答复】这场组会冻结了 {count} 份产物。{detail}你的问题已保存；改变方向请编辑并确认下一轮决定。"
            con.execute("INSERT INTO discussion VALUES(?,?,?,?,?)", (uuid.uuid4().hex, meeting_id, question, answer, time.time()))
            con.execute("UPDATE projects SET qa_used=qa_used+1 WHERE id=?", (p["id"],))
            self.event(con, p["id"], "meeting_question", {"meeting_id": meeting_id})
            return answer

    def confirm(self, meeting_id, expected_version, instruction, selected):
        instruction, selected = text(instruction, "下一轮方向"), scenario(selected)
        if type(expected_version) is not int:
            raise ValueError("计划版本应为整数")
        with self.connection(write=True) as con:
            m = self.row(con, "meetings", meeting_id)
            existing = con.execute("SELECT * FROM decisions WHERE meeting_id=?", (meeting_id,)).fetchone()
            if existing:
                if existing["instruction"] != instruction or existing["scenario"] != selected or existing["from_version"] != expected_version:
                    raise Conflict("这场组会已确认其他决定；重复确认只能重放原决定")
                return dict(existing)
            p = self.row(con, "projects", m["project_id"])
            if m["version"] != expected_version or p["version"] != expected_version:
                raise Conflict("计划已更新，请刷新后重新评审")
            new_version = expected_version+1
            decision = dict(id=uuid.uuid4().hex, meeting_id=meeting_id, project_id=p["id"], from_version=expected_version, to_version=new_version, instruction=instruction, scenario=selected, created=time.time())
            con.execute("INSERT INTO decisions VALUES(:id,:meeting_id,:project_id,:from_version,:to_version,:instruction,:scenario,:created)", decision)
            con.execute("UPDATE projects SET version=?,scenario=? WHERE id=?", (new_version, selected, p["id"]))
            con.execute("UPDATE tasks SET status='cancelled' WHERE project_id=? AND status='queued' AND version<?", (p["id"], new_version))
            con.execute("UPDATE meetings SET status='closed' WHERE id=?", (meeting_id,))
            self.add_round(con, p["id"], new_version, instruction, selected)
            self.event(con, p["id"], "decision_confirmed", decision)
            return decision
