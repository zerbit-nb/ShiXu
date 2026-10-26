"""Synthetic demo and UI regression fixture. Never opens the user's database or capture worker."""
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from app.config import Settings
import app.main as main
from app.schemas import TaskFields
from tests.test_api import LocalModelStub


def make_app(folder, baseline=None):
    if baseline:
        main.STATIC=Path(baseline)/'app'/'static'
    app=main.create_app(Settings(),db_path=folder/'db.sqlite3',config_path=folder/'config.json',llm=LocalModelStub())
    original=app.router.lifespan_context
    @asynccontextmanager
    async def isolated(application):
        async with original(application):
            db=application.state.db
            today=datetime.now(timezone(timedelta(hours=8))).date()
            db.conn.execute("INSERT INTO wechat_streams VALUES ('fixture','fixture-profile',?, ?,1)",('a'*64,'b'*64))
            db.conn.commit()
            def message(source,text,status='ready',sender='林同学'):
                row=db.create_message(dict(source=source,source_group={'qq':'软件工程课程群','wechat':'校园志愿者群','manual':'个人安排'}[source],sender=sender,sent_at='2026-10-18T09:30:00+08:00',raw_text=text,extraction_status=status))
                if source=='qq':
                    db.conn.execute('INSERT INTO qq_receipts VALUES (?,?,?,?)',('12345678','87654321',row['id'],row['id']));db.conn.commit()
                if source=='wechat':
                    number=db.conn.execute("SELECT count(*) FROM wechat_receipts").fetchone()[0]+1
                    db.conn.execute("INSERT INTO wechat_receipts VALUES ('fixture','message_0.db',?,?,?,?)",(number,'c'*64,row['id'],row['created_at']))
                    db.conn.commit()
                return row
            def task(source,title,days,text,**extra):
                m=message(source,text)
                fields=TaskFields(title=title,deadline=(today+timedelta(days=days)).isoformat() if days is not None else None,**extra).model_dump(mode='json')
                draft=db.create_draft(m['id'],fields,[])
                return db.confirm_draft(draft['id'],fields)
            first=task('qq','提交软件工程项目阶段报告',-1,'【课程通知】请在周五前提交项目阶段报告，包含需求分析、原型及本周进度。提交到课程平台，文件名为学号与姓名。',priority='high',materials=['阶段报告','界面原型'],submit_method='课程平台',format_requirement='PDF',description='核对需求分析和界面原型，整理本周进度。')
            second=message('wechat','补充说明：阶段报告需附上测试清单。<img src=x onerror=alert(1)>')
            draft=db.create_draft(second['id'],TaskFields(title='报告补充材料').model_dump(mode='json'),[]);db.link_draft(draft['id'],first['id'])
            task('wechat','确认周末志愿服务名单',0,'请核对周末志愿服务名单，并于今晚确认参与时间。',location='学生服务中心',priority='high')
            task('qq','准备数据库课程小组展示',0,'下次课进行小组展示，请准备演示文件。',description='整理演示步骤，检查数据与图表。')
            task('manual','整理本周阅读笔记',2,'手动创建的待办')
            task('wechat','提交校园活动报名材料',4,'校园活动报名开始，请准备材料并按时提交。',materials=['报名表'])
            task('manual','确认下学期选修课程安排',None,'个人安排：确认下学期选修课程安排。')
            task('qq','长标题测试：'+('课程项目的需求分析与实现细节需要逐项核对，' * 6),7,'长中文和换行测试。\n原文需要完整展示。')
            done=task('manual','完成上周课程复盘',-2,'上周课程复盘。');db.update_task(done['id'],{'status':'completed'})
            for i in range(34):message('qq' if i%2 else 'wechat','收件箱分页测试 '+str(i),'received',sender='测试成员')
            message('qq','bad','failed')
            message('manual','bad','failed')
            message('wechat','无需处理的活动闲聊','ignored')
            message('qq','讨论记录，无需行动','no_action')
            yield
    app.router.lifespan_context=isolated
    return app
