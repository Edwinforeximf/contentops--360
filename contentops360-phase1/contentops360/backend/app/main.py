import os
import json
from datetime import datetime, timezone, timedelta
from typing import Optional
from contextlib import asynccontextmanager
import jwt
from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import inspect, text, create_engine, Column, Integer, String, DateTime, ForeignKey, Text, Boolean, select, func
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from pwdlib import PasswordHash

DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./local.db').replace('postgresql://','postgresql+psycopg://',1)
SECRET = os.getenv('JWT_SECRET','')
if not SECRET or len(SECRET) < 32:
    raise RuntimeError('Set JWT_SECRET to a random value of at least 32 characters')
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args={'check_same_thread':False} if DATABASE_URL.startswith('sqlite') else {})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()
hasher = PasswordHash.recommended()
now = lambda: datetime.now(timezone.utc)

class AppSetting(Base):
    __tablename__='app_settings'
    key=Column(String(100),primary_key=True)
    value=Column(Text,nullable=False)

class User(Base):
    __tablename__='users'
    id=Column(Integer,primary_key=True); email=Column(String(255),unique=True,nullable=False); name=Column(String(120),nullable=False); password_hash=Column(Text,nullable=False); role=Column(String(32),nullable=False,default='content'); active=Column(Boolean,default=True)
class Project(Base):
    __tablename__='projects'
    id=Column(Integer,primary_key=True); title=Column(String(200),nullable=False); description=Column(Text,default=''); created_by=Column(Integer,ForeignKey('users.id')); created_at=Column(DateTime(timezone=True),default=now)
class Task(Base):
    __tablename__='tasks'
    id=Column(Integer,primary_key=True); project_id=Column(Integer,ForeignKey('projects.id'),nullable=False); title=Column(String(200),nullable=False); stage=Column(String(32),default='content'); status=Column(String(32),default='todo'); assignee_id=Column(Integer,ForeignKey('users.id')); planned_start=Column(DateTime(timezone=True)); planned_end=Column(DateTime(timezone=True)); actual_start=Column(DateTime(timezone=True)); actual_end=Column(DateTime(timezone=True)); asset_url=Column(Text,default=''); notes=Column(Text,default=''); card_color=Column(String(7),default='#ffffff'); priority=Column(String(20),default='medium'); creative_type=Column(String(40),default='video_ads'); stage_pics=Column(Text,default='{}'); created_at=Column(DateTime(timezone=True),default=now)
class StageRun(Base):
    __tablename__='stage_runs'
    id=Column(Integer,primary_key=True)
    task_id=Column(Integer,ForeignKey('tasks.id'),nullable=False,index=True)
    stage=Column(String(32),nullable=False)
    assignee_id=Column(Integer,ForeignKey('users.id'),nullable=False)
    status=Column(String(32),nullable=False,default='pending_acceptance')
    received_at=Column(DateTime(timezone=True),default=now)
    accepted_at=Column(DateTime(timezone=True))
    completed_at=Column(DateTime(timezone=True))
    planned_end=Column(DateTime(timezone=True))

class TimeEntry(Base):
    __tablename__='time_entries'
    id=Column(Integer,primary_key=True); task_id=Column(Integer,ForeignKey('tasks.id'),nullable=False); user_id=Column(Integer,ForeignKey('users.id'),nullable=False); started_at=Column(DateTime(timezone=True),nullable=False); stopped_at=Column(DateTime(timezone=True))
class Review(Base):
    __tablename__='reviews'
    id=Column(Integer,primary_key=True); task_id=Column(Integer,ForeignKey('tasks.id'),nullable=False); reviewer_id=Column(Integer,ForeignKey('users.id'),nullable=False); decision=Column(String(20),nullable=False); comment=Column(Text,default=''); created_at=Column(DateTime(timezone=True),default=now)
class Event(Base):
    __tablename__='task_events'
    id=Column(Integer,primary_key=True); task_id=Column(Integer,ForeignKey('tasks.id'),nullable=False); actor_id=Column(Integer,ForeignKey('users.id'),nullable=False); action=Column(String(80)); detail=Column(Text,default=''); created_at=Column(DateTime(timezone=True),default=now)

@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(bind=engine)
    # Additive migration: preserve existing tasks, users, and stage history.
    with engine.begin() as conn:
        if 'card_color' not in [x['name'] for x in inspect(conn).get_columns('tasks')]:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN card_color VARCHAR(7) DEFAULT '#ffffff'"))
        for col,sql in [('priority',"ALTER TABLE tasks ADD COLUMN priority VARCHAR(20) DEFAULT 'medium'"),('creative_type',"ALTER TABLE tasks ADD COLUMN creative_type VARCHAR(40) DEFAULT 'video_ads'"),('stage_pics',"ALTER TABLE tasks ADD COLUMN stage_pics TEXT DEFAULT '{}' ")]:
            if col not in [x['name'] for x in inspect(conn).get_columns('tasks')]:conn.execute(text(sql))
    # Non-destructive migration for existing Phase 1 tasks.
    with SessionLocal() as s:
        existing=s.scalars(select(Task)).all()
        for t in existing:
            has_run=s.scalar(select(StageRun.id).where(StageRun.task_id==t.id).limit(1))
            if not has_run and t.assignee_id:
                state='approved' if t.status=='approved' else ('completed_work' if t.status in ['ready_for_review','stage_complete'] else 'accepted')
                s.add(StageRun(task_id=t.id,stage=t.stage,assignee_id=t.assignee_id,status=state,received_at=t.created_at or now(),accepted_at=t.actual_start or t.created_at or now(),planned_end=t.planned_end))
        s.commit()
    yield
app=FastAPI(title='ContentOps 360 API', lifespan=lifespan)
origins=[x.strip() for x in os.getenv('CORS_ORIGINS','http://localhost:3000').split(',') if x.strip()]
app.add_middleware(CORSMiddleware,allow_origins=origins,allow_credentials=False,allow_methods=['GET','POST','PATCH'],allow_headers=['Authorization','Content-Type'])
def db():
    with SessionLocal() as s: yield s

def token(user): return jwt.encode({'sub':str(user.id),'exp':now()+timedelta(days=7)},SECRET,algorithm='HS256')
def current(authorization:Optional[str]=Header(None),s:Session=Depends(db)):
    if not authorization or not authorization.startswith('Bearer '): raise HTTPException(401,'Login required')
    try: uid=int(jwt.decode(authorization[7:],SECRET,algorithms=['HS256'])['sub'])
    except Exception: raise HTTPException(401,'Invalid token')
    user=s.get(User,uid)
    if not user or not user.active: raise HTTPException(401,'User unavailable')
    return user

def require(user,roles):
    if user.role not in roles: raise HTTPException(403,'Insufficient permission')
def stamp(v): return v.isoformat() if v else None
def user_json(u): return {'id':u.id,'email':u.email,'name':u.name,'role':u.role}
def project_json(p): return {'id':p.id,'title':p.title,'description':p.description,'created_at':stamp(p.created_at)}
def task_json(t,s):
    entries=s.scalars(select(TimeEntry).where(TimeEntry.task_id==t.id)).all()
    seconds=sum(max(0,((e.stopped_at or now())-e.started_at).total_seconds()) for e in entries)
    run=s.scalar(select(StageRun).where(StageRun.task_id==t.id,StageRun.completed_at.is_(None)).order_by(StageRun.id.desc()))
    stage_seconds=0
    if run:
        stage_seconds=sum(max(0,((e.stopped_at or now())-e.started_at).total_seconds()) for e in entries if e.user_id==run.assignee_id and e.started_at >= (run.accepted_at or run.received_at))
    return {'handoff_status':run.status if run else None,'stage_run_id':run.id if run else None,'stage_seconds':round(stage_seconds),'id':t.id,'project_id':t.project_id,'title':t.title,'stage':t.stage,'status':t.status,'assignee_id':t.assignee_id,'planned_start':stamp(t.planned_start),'planned_end':stamp(t.planned_end),'actual_start':stamp(t.actual_start),'actual_end':stamp(t.actual_end),'asset_url':t.asset_url,'notes':t.notes,'card_color':t.card_color or '#ffffff','priority':t.priority or 'medium','creative_type':t.creative_type or 'video_ads','stage_pics':json.loads(t.stage_pics or '{}'),'tracked_seconds':round(seconds),'timer_running':any(e.stopped_at is None for e in entries)}

class LoginIn(BaseModel): email:str; password:str
class SetupIn(LoginIn): name:str=Field(min_length=2)
class UserIn(SetupIn): role:str='content'
class ProjectIn(BaseModel): title:str=Field(min_length=2); description:str=''
class TaskIn(BaseModel): project_id:int; title:str=Field(min_length=2); stage:str='content'; assignee_id:Optional[int]=None; planned_start:Optional[datetime]=None; planned_end:Optional[datetime]=None; notes:str=''; asset_url:str=''; priority:str='medium'; creative_type:str='video_ads'; stage_pics:dict[str,list[int]]=Field(default_factory=dict)
class TaskPatch(BaseModel): priority:Optional[str]=None; creative_type:Optional[str]=None; stage_pics:Optional[dict[str,list[int]]]=None; card_color:Optional[str]=None; title:Optional[str]=None; stage:Optional[str]=None; assignee_id:Optional[int]=None; planned_start:Optional[datetime]=None; planned_end:Optional[datetime]=None; notes:Optional[str]=None; asset_url:Optional[str]=None
class ReviewIn(BaseModel): decision:str; comment:str=''

DEFAULT_SETTINGS={'app_name':'ContentOps 360','subtitle':'PRODUCTION WORKSPACE','login_title':'Masuk ke dashboard','login_description':'Production timeline, approval, dan KPI dalam satu workspace.','primary_color':'#2859e5','accent_color':'#69a3ff','sidebar_color':'#0b1630','background_color':'#f5f7fb','stage_content_color':'#777777','stage_footage_color':'#287dcc','stage_editing_color':'#ad8526','stage_review_color':'#8055a5','stage_publish_color':'#27885e','stage_content_label':'Script','stage_footage_label':'Footage / Shooting','stage_editing_label':'Production','stage_review_label':'Review','stage_publish_label':'Done / Publish'}
class SettingsIn(BaseModel):
    app_name:str=Field(min_length=2,max_length=80)
    subtitle:str=Field(max_length=120)
    login_title:str=Field(max_length=120)
    login_description:str=Field(max_length=300)
    primary_color:str
    accent_color:str
    sidebar_color:str
    background_color:str
    stage_content_color:str='#777777'
    stage_footage_color:str='#287dcc'
    stage_editing_color:str='#ad8526'
    stage_review_color:str='#8055a5'
    stage_publish_color:str='#27885e'
    stage_content_label:str=Field(default='Script',min_length=2,max_length=50)
    stage_footage_label:str=Field(default='Footage / Shooting',min_length=2,max_length=50)
    stage_editing_label:str=Field(default='Production',min_length=2,max_length=50)
    stage_review_label:str=Field(default='Review',min_length=2,max_length=50)
    stage_publish_label:str=Field(default='Done / Publish',min_length=2,max_length=50)

@app.get('/settings')
def get_settings(s:Session=Depends(db)):
    result=DEFAULT_SETTINGS.copy()
    for row in s.scalars(select(AppSetting)):result[row.key]=row.value
    return result

@app.patch('/settings')
def update_settings(v:SettingsIn,s:Session=Depends(db),u:User=Depends(current)):
    require(u,['admin'])
    data=v.model_dump()
    import re
    for key in ['primary_color','accent_color','sidebar_color','background_color','stage_content_color','stage_footage_color','stage_editing_color','stage_review_color','stage_publish_color']:
        if not re.fullmatch(r'#[0-9a-fA-F]{6}',data[key]):raise HTTPException(400,'Invalid hex color: '+key)
    for key,value in data.items():
        row=s.get(AppSetting,key)
        if row:row.value=value
        else:s.add(AppSetting(key=key,value=value))
    s.commit()
    return get_settings(s)

@app.get('/health')
def health(): return {'ok':True}
@app.post('/auth/setup')
def setup(v:SetupIn,s:Session=Depends(db)):
    if s.scalar(select(func.count(User.id)))>0: raise HTTPException(403,'Setup already completed')
    if len(v.password)<10: raise HTTPException(400,'Password must be at least 10 characters')
    u=User(email=v.email.lower(),name=v.name,password_hash=hasher.hash(v.password),role='admin');s.add(u);s.commit();s.refresh(u)
    return {'token':token(u),'user':user_json(u)}
@app.post('/auth/login')
def login(v:LoginIn,s:Session=Depends(db)):
    u=s.scalar(select(User).where(User.email==v.email.lower()))
    if not u or not u.active or not hasher.verify(v.password,u.password_hash):raise HTTPException(401,'Invalid credentials')
    return {'token':token(u),'user':user_json(u)}
@app.get('/auth/me')
def me(u:User=Depends(current)):return user_json(u)
@app.get('/users')
def users(s:Session=Depends(db),u:User=Depends(current)):return [user_json(x) for x in s.scalars(select(User).order_by(User.name))]
@app.post('/users')
def add_user(v:UserIn,s:Session=Depends(db),u:User=Depends(current)):
    require(u,['admin'])
    if v.role not in ['admin','manager','content','educator','production','reviewer','social','ads','viewer']:raise HTTPException(400,'Invalid role')
    if len(v.password)<10:raise HTTPException(400,'Password too short')
    if s.scalar(select(User).where(User.email==v.email.lower())):raise HTTPException(409,'Email exists')
    x=User(name=v.name,email=v.email.lower(),password_hash=hasher.hash(v.password),role=v.role);s.add(x);s.commit();s.refresh(x);return user_json(x)
@app.get('/projects')
def projects(s:Session=Depends(db),u:User=Depends(current)):return [project_json(x) for x in s.scalars(select(Project).order_by(Project.id.desc()))]
@app.post('/projects')
def add_project(v:ProjectIn,s:Session=Depends(db),u:User=Depends(current)):
    require(u,['admin','manager','content']);p=Project(**v.model_dump(),created_by=u.id);s.add(p);s.commit();s.refresh(p);return project_json(p)
@app.get('/tasks')
def tasks(project_id:Optional[int]=None,s:Session=Depends(db),u:User=Depends(current)):
    q=select(Task).order_by(Task.id.desc())
    if project_id:q=q.where(Task.project_id==project_id)
    return [task_json(t,s) for t in s.scalars(q)]
def validate_task_meta(s,priority,creative_type,pics):
    if priority not in ['low','medium','high','urgent']:raise HTTPException(400,'Invalid priority')
    if creative_type not in ['video_ads','image_ads','reels','shorts','carousel','static_post','story','livestream','article','other']:raise HTTPException(400,'Invalid creative type')
    for stage,ids in pics.items():
        if stage not in ['content','footage','editing','review','publish'] or len(ids)>20 or len(ids)!=len(set(ids)):raise HTTPException(400,'Invalid stage PIC list')
        if any(not s.get(User,uid) for uid in ids):raise HTTPException(400,'PIC user not found')

@app.post('/tasks')
def add_task(v:TaskIn,s:Session=Depends(db),u:User=Depends(current)):
    require(u,['admin','manager','content'])
    if not s.get(Project,v.project_id):raise HTTPException(404,'Project not found')
    if v.stage not in ['content','footage','editing','review','publish']:raise HTTPException(400,'Invalid stage')
    if v.assignee_id and not s.get(User,v.assignee_id):raise HTTPException(400,'Assignee not found')
    if v.planned_start and v.planned_end and v.planned_end<=v.planned_start:raise HTTPException(400,'Deadline must follow start')
    if v.stage!='content':raise HTTPException(400,'New content must start in content stage')
    if not v.assignee_id:raise HTTPException(400,'Select a Content PIC')
    validate_task_meta(s,v.priority,v.creative_type,v.stage_pics)
    pics=dict(v.stage_pics);pics['content']=list(dict.fromkeys([v.assignee_id]+pics.get('content',[])))
    data=v.model_dump(exclude={'stage_pics'});t=Task(**data,stage_pics=json.dumps(pics));s.add(t);s.flush()
    s.add(StageRun(task_id=t.id,stage='content',assignee_id=v.assignee_id,status='pending_acceptance',planned_end=v.planned_end))
    s.add(Event(task_id=t.id,actor_id=u.id,action='created'));s.commit();s.refresh(t);return task_json(t,s)
@app.patch('/tasks/{task_id}')
def patch_task(task_id:int,v:TaskPatch,s:Session=Depends(db),u:User=Depends(current)):
    t=s.get(Task,task_id)
    if not t:raise HTTPException(404,'Task not found')
    if u.role not in ['admin','manager'] and t.assignee_id!=u.id:raise HTTPException(403,'Not assigned')
    if t.status in ['approved','published'] and u.role not in ['admin','manager']:raise HTTPException(409,'Task locked')
    changes=v.model_dump(exclude_unset=True)
    if 'stage' in changes:raise HTTPException(409,'Use handoff endpoint to move stages')
    if 'assignee_id' in changes:raise HTTPException(409,'Use handoff endpoint to change PIC')
    if 'assignee_id' in changes and changes['assignee_id'] is not None and not s.get(User,changes['assignee_id']):raise HTTPException(400,'Assignee not found')
    if 'card_color' in changes and (changes['card_color'] is None or not __import__('re').fullmatch(r'#[0-9a-fA-F]{6}',changes['card_color'])):raise HTTPException(400,'Invalid card color')
    if 'card_color' in changes and u.role!='admin':raise HTTPException(403,'Only admin can change card color')
    if any(k in changes for k in ['priority','creative_type','stage_pics']):
        validate_task_meta(s,changes.get('priority',t.priority or 'medium'),changes.get('creative_type',t.creative_type or 'video_ads'),changes.get('stage_pics',json.loads(t.stage_pics or '{}')))
    if 'stage_pics' in changes:
        if u.role not in ['admin','manager']:raise HTTPException(403,'Only admin or manager can edit stage PICs')
        changes['stage_pics']=json.dumps(changes['stage_pics'])
    for k,val in changes.items():setattr(t,k,val)
    if t.planned_start and t.planned_end and t.planned_end<=t.planned_start:raise HTTPException(400,'Invalid deadline')
    s.add(Event(task_id=t.id,actor_id=u.id,action='updated',detail=','.join(changes)));s.commit();return task_json(t,s)

def assigned(t,u):
    if u.role not in ['admin','manager'] and t.assignee_id!=u.id:raise HTTPException(403,'Not assigned')
@app.post('/tasks/{task_id}/timer/{action}')
def timer(task_id:int,action:str,s:Session=Depends(db),u:User=Depends(current)):
    t=s.get(Task,task_id)
    if not t:raise HTTPException(404,'Task not found')
    assigned(t,u)
    if t.status in ['approved','published']:raise HTTPException(409,'Task already finalized')
    run=s.scalar(select(StageRun).where(StageRun.task_id==task_id,StageRun.completed_at.is_(None)).order_by(StageRun.id.desc()))
    if not run or run.status!='accepted':raise HTTPException(409,'PIC must accept the handoff first')
    open_entry=s.scalar(select(TimeEntry).where(TimeEntry.task_id==task_id,TimeEntry.user_id==u.id,TimeEntry.stopped_at.is_(None)))
    if action in ['start','resume']:
        if open_entry:raise HTTPException(409,'Timer already running')
        if t.status not in ['todo','in_progress','revision']:raise HTTPException(409,'Task not in work state')
        if not t.actual_start:t.actual_start=now()
        t.status='in_progress';s.add(TimeEntry(task_id=task_id,user_id=u.id,started_at=now()))
    elif action in ['pause','stop']:
        if not open_entry:raise HTTPException(409,'Timer not running')
        open_entry.stopped_at=now()
        if action=='stop':
            t.status='stage_complete' if t.stage in ['content','footage','editing'] else 'ready_for_review'
            t.actual_end=now()
            run.status='completed_work'
    else:raise HTTPException(400,'Invalid action')
    s.add(Event(task_id=task_id,actor_id=u.id,action='timer_'+action));s.commit();return task_json(t,s)

class HandoffIn(BaseModel):
    next_stage:str
    assignee_id:int
    planned_end:Optional[datetime]=None
    planned_start:Optional[datetime]=None

@app.post('/tasks/{task_id}/accept')
def accept_handoff(task_id:int,s:Session=Depends(db),u:User=Depends(current)):
    t=s.get(Task,task_id)
    if not t:raise HTTPException(404,'Task not found')
    run=s.scalar(select(StageRun).where(StageRun.task_id==task_id,StageRun.completed_at.is_(None)).order_by(StageRun.id.desc()))
    if not run or run.status!='pending_acceptance':raise HTTPException(409,'No pending handoff')
    if run.assignee_id!=u.id:raise HTTPException(403,'Only assigned PIC can accept')
    run.status='accepted';run.accepted_at=now();t.status='todo'
    s.add(Event(task_id=task_id,actor_id=u.id,action='handoff_accepted',detail=run.stage))
    s.commit();return task_json(t,s)

@app.post('/tasks/{task_id}/handoff')
def handoff(task_id:int,v:HandoffIn,s:Session=Depends(db),u:User=Depends(current)):
    t=s.get(Task,task_id)
    if not t:raise HTTPException(404,'Task not found')
    stages=['content','footage','editing','review','publish']
    if t.stage not in stages or t.stage=='publish':raise HTTPException(409,'No further stage')
    if v.next_stage!=stages[stages.index(t.stage)+1]:raise HTTPException(409,'Only next stage allowed')
    run=s.scalar(select(StageRun).where(StageRun.task_id==task_id,StageRun.completed_at.is_(None)).order_by(StageRun.id.desc()))
    if not run or run.status not in ['completed_work','approved']:raise HTTPException(409,'Complete current stage before handoff')
    if u.id!=t.assignee_id and u.role not in ['admin','manager']:raise HTTPException(403,'Not assigned')
    if s.scalar(select(TimeEntry.id).where(TimeEntry.task_id==task_id,TimeEntry.stopped_at.is_(None))):raise HTTPException(409,'Pause all timers first')
    if v.planned_start and v.planned_end and v.planned_end<=v.planned_start:raise HTTPException(400,'Deadline must follow start')
    pic=s.get(User,v.assignee_id)
    if not pic or not pic.active:raise HTTPException(400,'Invalid PIC')
    if t.stage=='review' and t.status!='approved':raise HTTPException(409,'Reviewer approval required')
    run.status='completed';run.completed_at=now()
    old=t.stage;t.stage=v.next_stage;t.assignee_id=pic.id;t.status='pending_acceptance'
    t.actual_start=None;t.actual_end=None
    t.planned_start=v.planned_start;t.planned_end=v.planned_end
    pics=json.loads(t.stage_pics or '{}');pics[v.next_stage]=list(dict.fromkeys([pic.id]+pics.get(v.next_stage,[])));t.stage_pics=json.dumps(pics)
    s.add(StageRun(task_id=task_id,stage=v.next_stage,assignee_id=pic.id,status='pending_acceptance',planned_end=v.planned_end))
    s.add(Event(task_id=task_id,actor_id=u.id,action='handoff',detail=f'{old} -> {v.next_stage}; PIC {pic.id}'))
    s.commit();return task_json(t,s)

@app.get('/tasks/{task_id}/stages')
def stage_history(task_id:int,s:Session=Depends(db),u:User=Depends(current)):
    if not s.get(Task,task_id):raise HTTPException(404,'Task not found')
    return [{'stage':r.stage,'assignee_id':r.assignee_id,'status':r.status,'received_at':stamp(r.received_at),'accepted_at':stamp(r.accepted_at),'completed_at':stamp(r.completed_at),'planned_end':stamp(r.planned_end)} for r in s.scalars(select(StageRun).where(StageRun.task_id==task_id).order_by(StageRun.id))]

@app.post('/tasks/{task_id}/review')
def review(task_id:int,v:ReviewIn,s:Session=Depends(db),u:User=Depends(current)):
    require(u,['admin','manager','reviewer'])
    t=s.get(Task,task_id)
    if not t:raise HTTPException(404,'Task not found')
    if t.status!='ready_for_review':raise HTTPException(409,'Task must be ready for review')
    if v.decision not in ['approve','revision']:raise HTTPException(400,'Invalid decision')
    if v.decision=='revision' and not v.comment.strip():raise HTTPException(400,'Revision comment required')
    if t.stage!='review':raise HTTPException(409,'Review must happen in review stage')
    run=s.scalar(select(StageRun).where(StageRun.task_id==task_id,StageRun.completed_at.is_(None)).order_by(StageRun.id.desc()))
    if not run or run.status!='completed_work':raise HTTPException(409,'Review work must be completed first')
    t.status='approved' if v.decision=='approve' else 'revision'
    run.status='approved' if v.decision=='approve' else 'accepted'
    s.add(Review(task_id=t.id,reviewer_id=u.id,decision=v.decision,comment=v.comment));s.add(Event(task_id=t.id,actor_id=u.id,action='review_'+v.decision,detail=v.comment));s.commit();return task_json(t,s)
@app.post('/tasks/{task_id}/publish')
def publish(task_id:int,s:Session=Depends(db),u:User=Depends(current)):
    require(u,['admin','manager','social'])
    t=s.get(Task,task_id)
    if not t:raise HTTPException(404,'Task not found')
    if t.stage!='publish' or t.status not in ['stage_complete','ready_for_review']:raise HTTPException(409,'Publish stage must be completed first')
    t.status='published';s.add(Event(task_id=t.id,actor_id=u.id,action='published'));s.commit();return task_json(t,s)
@app.get('/tasks/{task_id}/history')
def history(task_id:int,s:Session=Depends(db),u:User=Depends(current)):
    if not s.get(Task,task_id):raise HTTPException(404,'Task not found')
    return [{'action':e.action,'detail':e.detail,'actor_id':e.actor_id,'at':stamp(e.created_at)} for e in s.scalars(select(Event).where(Event.task_id==task_id).order_by(Event.id.desc()))]
@app.get('/dashboard')
def dashboard(s:Session=Depends(db),u:User=Depends(current)):
    ts=s.scalars(select(Task)).all(); completed=[t for t in ts if t.status in ['approved','published']]
    ontime=[t for t in completed if t.actual_end and t.planned_end and t.actual_end<=t.planned_end]
    eligible=[t for t in completed if t.actual_end and t.planned_end]
    overdue=sum(1 for t in ts if t.planned_end and t.planned_end<now() and t.status not in ['approved','published'])
    return {'total_tasks':len(ts),'completed':len(completed),'overdue':overdue,'on_time_rate':round(100*len(ontime)/len(eligible),1) if eligible else None,'on_time_sample':len(eligible)}

@app.delete('/tasks/{task_id}')
def delete_task(task_id:int,s:Session=Depends(db),u:User=Depends(current)):
    require(u,['admin'])
    t=s.get(Task,task_id)
    if not t:raise HTTPException(404,'Task not found')
    for model in [TimeEntry,Review,Event,StageRun]:
        for item in s.scalars(select(model).where(model.task_id==task_id)).all():s.delete(item)
    s.delete(t);s.commit()
    return {'ok':True,'deleted_task_id':task_id}

class ClearBoardIn(BaseModel):
    confirmation:str
    project_id:Optional[int]=None

@app.post('/admin/clear-board')
def clear_board(v:ClearBoardIn,s:Session=Depends(db),u:User=Depends(current)):
    require(u,['admin'])
    if v.confirmation!='HAPUS SEMUA TASK':raise HTTPException(400,'Confirmation phrase mismatch')
    q=select(Task)
    if v.project_id is not None:
        if not s.get(Project,v.project_id):raise HTTPException(404,'Project not found')
        q=q.where(Task.project_id==v.project_id)
    target=s.scalars(q).all()
    for t in target:
        for model in [TimeEntry,Review,Event,StageRun]:
            for item in s.scalars(select(model).where(model.task_id==t.id)).all():s.delete(item)
        s.delete(t)
    s.commit()
    return {'ok':True,'deleted_tasks':len(target)}

class ProjectPatch(BaseModel):
    title:Optional[str]=Field(default=None,min_length=2,max_length=200)
    description:Optional[str]=None

@app.patch('/projects/{project_id}')
def update_project(project_id:int,v:ProjectPatch,s:Session=Depends(db),u:User=Depends(current)):
    require(u,['admin'])
    p=s.get(Project,project_id)
    if not p:raise HTTPException(404,'Project not found')
    for key,value in v.model_dump(exclude_unset=True).items():
        if value is not None:setattr(p,key,value)
    s.commit();return project_json(p)

class ProjectDeleteIn(BaseModel):
    confirmation:str

@app.post('/projects/{project_id}/delete')
def remove_project(project_id:int,v:ProjectDeleteIn,s:Session=Depends(db),u:User=Depends(current)):
    require(u,['admin'])
    p=s.get(Project,project_id)
    if not p:raise HTTPException(404,'Project not found')
    if v.confirmation!=f'HAPUS PROJECT {project_id}':raise HTTPException(400,'Confirmation phrase mismatch')
    task_ids=[t.id for t in s.scalars(select(Task).where(Task.project_id==project_id))]
    for task_id in task_ids:
        for model in [TimeEntry,Review,Event,StageRun]:
            for row in s.scalars(select(model).where(model.task_id==task_id)):s.delete(row)
        s.delete(s.get(Task,task_id))
    s.delete(p);s.commit()
    return {'ok':True,'deleted_project_id':project_id,'deleted_tasks':len(task_ids)}
