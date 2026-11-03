"""감사로그: 질의·근거·권한 판정·모델 버전 (PRD F3, 8장, 9-2).

원문 질의는 서비스 운영자(admin)만 볼 수 있고, 보존 기간이 지나면 원문만 지운다(해시는 남김).
"""
import hashlib
import json
from datetime import datetime, timedelta


class AuditLog:
    def __init__(self, db, now):
        self.db = db
        self.now = now

    def write(self, event, user_id=None, purpose=None, query=None, evidence=None,
              permission=None, model=None, outcome=None, flags=None):
        qh = hashlib.sha256(query.encode("utf-8")).hexdigest()[:16] if query else None
        return self.db.run(
            "INSERT INTO audit_logs(ts,user_id,purpose,event,query_text,query_hash,evidence,permission,model,outcome,flags)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (self.now(), user_id, purpose, event, query, qh,
             json.dumps(evidence or [], ensure_ascii=False), json.dumps(permission or {}, ensure_ascii=False),
             json.dumps(model or {}, ensure_ascii=False), outcome, json.dumps(flags or [], ensure_ascii=False)))

    def list(self, limit=200, raw=False, event=None):
        sql = "SELECT * FROM audit_logs"
        args = []
        if event:
            sql += " WHERE event=?"
            args.append(event)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(int(limit))
        rows = self.db.all(sql, args)
        for r in rows:
            for k in ("evidence", "permission", "model", "flags"):
                r[k] = json.loads(r[k] or "null")
            if not raw:
                q = r["query_text"]
                r["query_text"] = None if q is None else (q[:4] + "…(원문 열람 제한)")
        return rows

    def purge(self, raw_days, log_days):
        now = datetime.fromisoformat(self.now())
        raw_cut = (now - timedelta(days=raw_days)).isoformat(timespec="seconds")
        log_cut = (now - timedelta(days=log_days)).isoformat(timespec="seconds")
        with self.db.lock:
            a = self.db.conn.execute("UPDATE audit_logs SET query_text=NULL WHERE ts<? AND query_text IS NOT NULL",
                                     (raw_cut,)).rowcount
            b = self.db.conn.execute("DELETE FROM audit_logs WHERE ts<?", (log_cut,)).rowcount
            self.db.conn.commit()
        return {"raw_queries_cleared": a, "logs_deleted": b}
