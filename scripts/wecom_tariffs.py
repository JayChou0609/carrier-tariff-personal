#!/usr/bin/env python3
"""Shared tariff classification and group-robot delivery, credentials are supplied in memory."""
import argparse
import base64
import concurrent.futures
import csv
import datetime as dt
import fcntl
import hashlib
import html
import io
import json
import os
from pathlib import Path
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parent
PRIVATE = Path(os.environ.get('TARIFF_NOTIFY_STATE', str(Path(tempfile.gettempdir())/'wecom-notify-state')))
TZ = dt.timezone(dt.timedelta(hours=8))
SITE = 'https://jaychou0609.github.io/carrier-tariff-personal/'
API = 'https://qyapi.weixin.qq.com/cgi-bin/'
CARRIERS = {'mobile':'移动', 'telecom':'电信', 'unicom':'联通', 'gb':'广电'}
REGIONS = {'quanguo':'全国','jiangsu':'江苏','shanghai':'上海','zhejiang':'浙江',
           'hebei':'河北','henan':'河南','sichuan':'四川','guangdong':'广东','gansu':'甘肃'}
SCOPES = {'mobile':['quanguo','jiangsu','shanghai','gansu'],
          'telecom':['quanguo','jiangsu','shanghai','zhejiang'],
          'unicom':['quanguo','jiangsu','shanghai','hebei','henan','sichuan','guangdong'],
          'gb':['quanguo','jiangsu']}
BUCKETS = {'new':'今日上线', 'tomorrow_off':'明日下线', 'today_off':'今日下线'}


def now():
    return dt.datetime.now(TZ)


def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if '.private' in path.parts:
        os.chmod(path.parent, 0o700)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.saving-')
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, separators=(',', ':'))
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def config_hash(config):
    return digest({'mode':'robot','webhook':config['wecom_webhook']})


def validate_config(value):
    if not isinstance(value, dict):
        raise ValueError('请先填写企业微信群机器人的 Webhook 地址')
    webhook = str(value.get('wecom_webhook') or '').strip()
    parts = urllib.parse.urlsplit(webhook)
    query = urllib.parse.parse_qs(parts.query)
    if (parts.scheme != 'https' or parts.netloc != 'qyapi.weixin.qq.com'
            or parts.path != '/cgi-bin/webhook/send' or parts.fragment
            or set(query) != {'key'} or len(query['key']) != 1
            or not re.fullmatch(r'[A-Za-z0-9_-]{16,256}', query['key'][0])):
        raise ValueError('请填写完整企业微信群机器人地址：https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=…')
    if value.get('site_url', SITE) != SITE:
        raise ValueError('本程序仅使用既有资费站点')
    return {'mode':'robot','wecom_webhook':webhook,'site_url':SITE,
            'schedule':['00:00','12:00','18:00']}


def date_day(value):
    text = str(value or '').strip()
    try:
        if re.search(r'T.*(?:Z|[+-]\d{2}:?\d{2})$', text, re.I):
            return dt.datetime.fromisoformat(text.replace('Z','+00:00')).astimezone(TZ).date().isoformat()
        m = re.match(r'^(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})(?:日|\b)', text) or re.fullmatch(r'(\d{4})(\d{2})(\d{2})', text)
        return dt.date(*map(int, m.groups())).isoformat() if m else ''
    except ValueError:
        return ''


def business_date(raw, keys):
    fields = raw.get('fields') or raw.get('detail') or {}
    for key in keys:
        for data in [fields, raw]:
            value = date_day(data.get(key))
            if value:
                return value
    return ''


def clean(value):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]*>', ' ', str(value or '')))).strip()


def normalize(raw, sid, stamp):
    fields = raw.get('fields') or raw.get('detail') or {}
    carrier, region = sid.split(':')
    title = clean(raw.get('name') or raw.get('title') or fields.get('name')) or '未命名资费'
    report = clean(fields.get('方案编号') or fields.get('reportNo') or raw.get('id'))
    category = clean(fields.get('资费类型') or raw.get('firstLevel') or fields.get('codeType'))
    fee = clean(fields.get('资费标准') if 'fields' in raw else raw.get('fee', fields.get('feesStandard','')))
    unit = clean(fields.get('feeUnit'))
    on = business_date(raw, ['上线日期','onDate','onlineDay','startDate'])
    off = business_date(raw, ['下线日期','offDate','offineDay','offlineDay','endDate'])
    item = {'source':sid, 'carrier':CARRIERS[carrier], 'region':REGIONS[region],
            'title':title, 'report_no':report, 'category':category, 'fee':fee,
            'unit':unit, 'on_date':on, 'off_date':off, 'snapshot':stamp,
            'details':json.dumps(fields, ensure_ascii=False, sort_keys=True)}
    item['identity'] = digest([sid, str(raw.get('id') or ''), title, report,
                               category, str(fields.get('归属') or raw.get('secondLevel') or '')])
    # Capture timestamps and firstConfirmTimeStr do not define new launches.
    business_fields = {k:v for k,v in fields.items() if k not in ['firstConfirmTimeStr','firstConfirmTime','timestamp','captureTime']}
    item['version'] = digest([item['identity'], fee, unit, on, off, business_fields])
    item['lifecycle_key'] = json.dumps([str(raw.get('id') or ''),title,
        str(fields.get('归属') or raw.get('firstLevel') or ''),
        str(fields.get('资费类型') or raw.get('secondLevel') or '')],ensure_ascii=False,separators=(',',':'))
    return item


def fetch_json(url):
    req = urllib.request.Request(url, headers={'User-Agent':'TariffWeComLocal/1.0', 'Cache-Control':'no-cache'})
    with urllib.request.urlopen(req, timeout=25) as response:
        return json.load(response)


def collect(day=None, snapshot_root=None, state_dir=PRIVATE, loader=fetch_json):
    day = day or now().date()
    report = {'day':day.isoformat(), 'generated':now().isoformat(timespec='seconds'),
              'timezone':'Asia/Shanghai', 'buckets':{k:[] for k in BUCKETS}, 'sources':[]}
    targets = [('{}:{}'.format(c,r), ('data/' if c == 'mobile' else c+'/data/')+r+'.json')
               for c, regions in SCOPES.items() for r in regions]
    registry = read_json(Path(snapshot_root)/'data/lifecycle.json',{}) if snapshot_root else {}
    def work(target):
        sid, path = target
        cache = Path(state_dir)/'cache'/(sid.replace(':','-')+'.json')
        try:
            data = read_json(Path(snapshot_root)/path) if snapshot_root else loader(SITE+path)
            if not isinstance(data, dict) or not isinstance(data.get('items'), list) or not data['items']:
                raise ValueError('快照缺失或没有有效条目')
            if not snapshot_root:
                write_json(cache, data)
            status = 'local_preview' if snapshot_root else 'downloaded'
        except Exception as exc:
            try:
                data = read_json(cache)
            except (ValueError, OSError):
                data = None
            if not data or not isinstance(data.get('items'), list) or not data['items']:
                return {'id':sid,'status':'failed','error':type(exc).__name__}, []
            status = 'cached'
        stamp = str(data.get('timestamp') or '')[:80]
        rows = [normalize(x, sid, stamp) for x in data['items'] if isinstance(x, dict) and not x.get('manual')]
        events_by_key=((registry.get('sources') or {}).get(sid) or {}).get('items') or {}
        for row in rows:
            events=events_by_key.get(row['lifecycle_key']) or []
            if events:
                event=events[-1]
                row['reonline_date']=date_day(event.get('date'))
                row['reonline_basis']=str(event.get('basis') or '')
        if not rows:
            return {'id':sid,'status':'failed','error':'InvalidItems'}, []
        metadata = {'id':sid,'status':status,'snapshot':stamp,'count':len(rows)}
        try:
            captured = dt.datetime.fromisoformat(stamp.replace('Z','+00:00'))
            captured = captured.replace(tzinfo=TZ) if captured.tzinfo is None else captured
            metadata['age_hours'] = round((now()-captured).total_seconds()/3600,1)
            metadata['stale'] = metadata['age_hours'] > 24
        except ValueError:
            metadata['timestamp_unknown'] = True
        return metadata, rows
    usable = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for source, rows in pool.map(work, targets):
            report['sources'].append(source)
            if source['status'] == 'failed':
                continue
            usable += 1
            tomorrow = (day+dt.timedelta(days=1)).isoformat()
            for row in rows:
                if row['on_date'] == report['day']:
                    report['buckets']['new'].append(row)
                if row['off_date'] == report['day']:
                    report['buckets']['today_off'].append(row)
                if row['off_date'] == tomorrow:
                    report['buckets']['tomorrow_off'].append(row)
    if not usable:
        raise RuntimeError('全部数据源读取失败；不会把故障当作零条资费推送')
    for bucket, rows in report['buckets'].items():
        unique = {digest([x['identity'],x['version']]):x for x in rows}
        report['buckets'][bucket] = sorted(unique.values(), key=lambda x:(x['source'],x['title'],x['report_no']))
    return report


def csv_bytes(rows):
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(['运营商','地区','资费名称','方案编号','类型','资费标准','单位','官方上线日期','官方下线日期','快照时间','完整原始字段'])
    for x in rows:
        values = [x[k] for k in ['carrier','region','title','report_no','category','fee','unit','on_date','off_date','snapshot','details']]
        writer.writerow(["'"+str(v) if re.match(r'^\s*[=+@-]', str(v)) else v for v in values])
    return ('\ufeff'+output.getvalue()).encode('utf-8')


def save_report(report, folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    write_json(folder/'report.json', report)
    for key, rows in report['buckets'].items():
        path = folder/(BUCKETS[key]+'.csv')
        path.write_bytes(csv_bytes(rows))
    return folder


def clip(text, budget):
    return str(text).encode('utf-8')[:budget].decode('utf-8','ignore')


def summary(report, key, pending):
    total = len(report['buckets'][key])
    lines = ['【{}】{}'.format(BUCKETS[key], report['day']),
             '按官方{}日期统计 · 北京时间'.format('上线' if key == 'new' else '下线'),
             '当前合计 {} 条；本次新增/变更提醒 {} 条。'.format(total, len(pending))]
    if key == 'tomorrow_off':
        lines.append('下线日期：'+(dt.date.fromisoformat(report['day'])+dt.timedelta(days=1)).isoformat())
    if key == 'today_off':
        lines.append('下线日当天仍按当日有效处理。')
    if not report['buckets'][key]:
        lines.append('当前快照没有匹配的资费。')
    elif not pending:
        lines.append('较前次没有新的条目或资费变更。')
    imperfect = [s for s in report['sources'] if s['status'] in ['failed','cached'] or s.get('stale') or s.get('timestamp_unknown')]
    lines.append('数据：{} / {} 个源可用；异常/缓存/超过24小时 {} 个。'.format(
                 sum(s['status'] != 'failed' for s in report['sources']),len(report['sources']),len(imperfect)))
    if imperfect:
        lines.append('需留意：'+', '.join(s['id'] for s in imperfect[:5]))
    stamps = sorted({s['snapshot'] for s in report['sources'] if s.get('snapshot')})
    if stamps:
        lines.append('源快照时间：'+stamps[0]+(' ～ '+stamps[-1] if len(stamps)>1 else ''))
    if report.get('collection_run'):
        lines.append('本轮采集批次：'+report['collection_run'])
    for row in pending[:6]:
        lines.append('{}{}｜{}｜{} {}｜编号 {}'.format(row['region'], row['carrier'],
                     clip(row['title'],110), clip(row['fee'],80), row['unit'], row['report_no'] or '未提供'))
    if pending:
        lines.append('完整本次明细见随后发送的 CSV 附件。')
    lines.append('快照可能延迟；快照时间保留在附件，办理以官方为准。')
    lines.append(SITE+'custom/')
    return clip('\n'.join(lines),1900)


class WeComError(RuntimeError):
    pass


class Client:
    def __init__(self, config):
        self.config = validate_config(config)
        self.key = urllib.parse.parse_qs(urllib.parse.urlsplit(self.config['wecom_webhook']).query)['key'][0]
        self.next_send=0

    def redact(self, text):
        for value in [self.config['wecom_webhook'], self.key]:
            text = text.replace(value, '[已隐藏]')
        return text

    def request(self, path, data, headers=None):
        url = API+path
        if not isinstance(data, bytes):
            data = json.dumps(data, ensure_ascii=False).encode()
            headers = {'Content-Type':'application/json; charset=utf-8'}
        req = urllib.request.Request(url, data=data, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=35) as response:
                value = json.load(response)
        except urllib.error.HTTPError as exc:
            raise WeComError('企业微信接口 HTTP '+str(exc.code)) from None
        except Exception as exc:
            raise WeComError('企业微信连接失败：'+type(exc).__name__) from None
        if not isinstance(value, dict) or 'errcode' not in value:
            raise WeComError('企业微信返回格式无效，未确认发送成功')
        if value['errcode'] != 0:
            raise WeComError(self.redact('企业微信 errcode={}：{}'.format(value.get('errcode'),str(value.get('errmsg',''))[:500])))
        return value

    def send(self, kind, body):
        if os.environ.get('WECOM_TARIFF_CARDS')=='1':
            time.sleep(max(0,self.next_send-time.monotonic()))
            self.next_send=time.monotonic()+3.3
        value = self.request('webhook/send?key='+urllib.parse.quote(self.key), {'msgtype':kind,kind:body})
        return value.get('msgid','accepted')

    def upload_csv(self, filename, content):
        if len(content) > 18*1024*1024:
            raise WeComError('明细文件过大，请先缩小数据范围')
        boundary = 'Tariff'+uuid.uuid4().hex
        filename = re.sub(r'[^A-Za-z0-9_.-]','_',filename)
        head = ('--'+boundary+'\r\nContent-Disposition: form-data; name="media"; filename="'+filename+'"\r\nContent-Type: text/csv\r\n\r\n').encode()
        payload = head+content+('\r\n--'+boundary+'--\r\n').encode()
        value = self.request('webhook/upload_media?key='+urllib.parse.quote(self.key)+'&type=file',
                             payload, {'Content-Type':'multipart/form-data; boundary='+boundary})
        if not value.get('media_id'):
            raise WeComError('企业微信未返回附件 media_id')
        return value['media_id']


def send_report(report, config, state_dir=PRIVATE, client=None):
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_fd = os.open(state_dir/'run.lock', os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(lock_fd, 'a+') as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'status':'already_running','sent':0}
        return _send_report(report,config,state_dir,client)


def _send_report(report, config, state_dir=PRIVATE, client=None):
    config = validate_config(config)
    state_dir = Path(state_dir)
    scope = config_hash(config)
    blocked = read_json(state_dir/'blocked.json', {})
    if blocked.get('scope') == scope:
        raise WeComError('上次推送失败已停止自动重试，请检查机器人配置和网络后在配置页重新发送测试消息')
    verified = read_json(state_dir/'ready.json', {})
    if verified.get('scope') != scope:
        return {'status':'not_verified','sent':0,'message':'请先在本机配置页发送测试消息，确认目标群能收到'}
    client = client or Client(config)
    ledger_path = state_dir/'delivery.json'
    ledger = read_json(ledger_path, {})
    delivered = 0
    cards_enabled=os.environ.get('WECOM_TARIFF_CARDS')=='1'
    slot = next(x for x in [18,12,0] if now().hour >= x)
    for key in BUCKETS:
        rows = report['buckets'][key]
        ledger_key = '|'.join([scope, report['day'], key])
        known = ledger.get(ledger_key, {'versions':[], 'zero_sent':False, 'slots':[]})
        versions = {digest([x['identity'],x['version']]):x for x in rows}
        pending = [x for version,x in versions.items() if version not in set(known['versions'])]
        pending_cards=[(v,x) for v,x in versions.items() if v not in known.get('card_versions',[])] if cards_enabled else []
        collection = report.get('collection_run','')
        already_reported = (collection in known.get('collections',[]) if collection
                            else slot in known.get('slots',[]))
        if not pending and not pending_cards and already_reported:
            continue
        delivery_id = digest([ledger_key, slot, collection, sorted(versions), sorted(digest([x['identity'],x['version']]) for x in pending),cards_enabled])
        path = state_dir/'outbox'/(delivery_id+'.json')
        outbox = read_json(path)
        if not outbox:
            outbox = {'text':summary(report,key,pending)+'\n报告时段：{:02d}:00'.format(slot),'summary_sent':False,'file_sent':False,'file_required':bool(pending)}
            write_json(path,outbox)
        try:
            if not outbox['summary_sent']:
                client.send('text', {'content':outbox['text']})
                outbox['summary_sent'] = True
                write_json(path,outbox)
                delivered += 1
            if pending_cards:
                from wecom_cards import render_card,text_card
                for version,row in pending_cards:
                    progress=outbox.setdefault('cards',{}).setdefault(version,{'image':False,'text':False})
                    if not progress['image']:
                        content=render_card(row,BUCKETS[key])
                        client.send('image',{'base64':base64.b64encode(content).decode(),
                            'md5':hashlib.md5(content).hexdigest()})
                        progress['image']=True;write_json(path,outbox);delivered+=1
                    if not progress['text']:
                        client.send('text',{'content':text_card(row,BUCKETS[key])})
                        progress['text']=True;write_json(path,outbox);delivered+=1
                    known['card_versions']=sorted(set(known.get('card_versions',[]))|{version})
                    ledger[ledger_key]=known;write_json(ledger_path,ledger)
            if pending and not outbox['file_sent']:
                media = client.upload_csv(key+'-'+report['day']+'.csv', csv_bytes(pending))
                client.send('file', {'media_id':media})
                outbox['file_sent'] = True
                write_json(path,outbox)
                delivered += 1
        except WeComError:
            # Avoid repeating successful recipients or summaries every six hours.
            write_json(state_dir/'blocked.json', {'scope':scope,'at':now().isoformat(),'delivery':delivery_id})
            raise
        known['versions'] = sorted(set(known['versions']) | set(versions))
        known['slots'] = sorted(set(known.get('slots', [])) | {slot})
        if collection:
            known['collections'] = sorted(set(known.get('collections',[])) | {collection})
        known['zero_sent'] = known['zero_sent'] or not rows
        ledger[ledger_key] = known
        write_json(ledger_path, ledger)
    return {'status':'sent' if delivered else 'unchanged','sent':delivered,
            'counts':{k:len(v) for k,v in report['buckets'].items()}}


def test_delivery(config, state_dir=PRIVATE):
    config = validate_config(config)
    client = Client(config)
    client.send('text', {'content':'【运营商资费提醒】企业微信群机器人连接测试\n接收范围为此 Webhook 对应的目标群。\n正式提醒：每日新增资费、今日下线、明日下线。\n时间：北京时间 00:00、12:00、18:00。\n'+SITE+'custom/'})
    write_json(Path(state_dir)/'ready.json', {'scope':config_hash(config),'verifiedAt':now().isoformat()})
    blocked = Path(state_dir)/'blocked.json'
    if blocked.exists():
        blocked.unlink()
    return {'status':'verified','message':'企业微信已接受测试消息，请在目标群核对机器人消息'}

