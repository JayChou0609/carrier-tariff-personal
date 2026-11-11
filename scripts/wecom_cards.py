"""Deterministic Chinese tariff cards; no webhook or other credential is rendered."""
import io
import json
import os
from pathlib import Path


def card_fields(row):
    fields=json.loads(row.get('details') or '{}')
    return [
        ('运营商',row['region']+row['carrier']),
        ('方案编号',row.get('report_no') or '未公示'),
        ('资费标准',(row.get('fee') or '未公示')+(' '+row['unit'] if row.get('unit') else '')),
        ('适用范围',str(fields.get('适用范围') or fields.get('applicablePeople') or '未公示')),
        ('适用地区',str(fields.get('适用地区') or row['region'])),
        ('上线日期',row.get('on_date') or '未公示'),
        ('重新上线日期',row.get('reonline_date') or '无已确认记录'),
        ('下线日期',row.get('off_date') or '未公示'),
        ('官方确认时间',str(fields.get('firstConfirmTimeStr') or '未公示')),
    ]


def text_card(row,label):
    lines=['【'+label+'】'+row['title']]
    lines.extend(k+'：'+v for k,v in card_fields(row))
    if row.get('reonline_basis'):lines.append('重新上线依据：'+row['reonline_basis'])
    lines.extend(['官方确认时间不单独作为二次上线证明。','本轮采集时间：'+row.get('snapshot','未提供')])
    return '\n'.join(lines).encode('utf8')[:1900].decode('utf8','ignore')


def font_path():
    candidates=[os.environ.get('TARIFF_CARD_FONT',''),
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        '/System/Library/Fonts/STHeiti Medium.ttc']
    return next((x for x in candidates if x and Path(x).is_file()),None)


def render_card(row,label):
    from PIL import Image,ImageDraw,ImageFont
    path=font_path()
    if not path:raise RuntimeError('未找到中文字体，停止图片发送')
    fonts={n:ImageFont.truetype(path,n) for n in [22,26,30,34,42]}
    probe=ImageDraw.Draw(Image.new('RGB',(1,1)))
    def wrap(text,size,width):
        result=[];line=''
        for ch in str(text):
            if ch=='\n' or probe.textlength(line+ch,font=fonts[size])>width:
                if line:result.append(line)
                line='' if ch=='\n' else ch
            else:line+=ch
        if line:result.append(line)
        return result or ['未公示']
    title=wrap(row['title'],42,820)
    rows=[(k,wrap(v[:500],30,600)) for k,v in card_fields(row)]
    y=170+len(title)*60
    height=y+sum(max(62,len(lines)*44+22) for _,lines in rows)+190
    canvas=Image.new('RGB',(1000,height),'#edf3fa');d=ImageDraw.Draw(canvas)
    color={'mobile':'#1677dd','unicom':'#ce2639','telecom':'#2457ad','gb':'#7145b2'}.get(row['source'].split(':')[0],'#1677dd')
    d.rounded_rectangle((28,28,972,height-28),radius=26,fill='white')
    d.rounded_rectangle((58,58,350,112),radius=15,fill=color)
    d.text((80,67),label,font=fonts[30],fill='white')
    d.text((580,72),row['region']+row['carrier'],font=fonts[30],fill=color)
    pos=155
    for line in title:d.text((70,pos),line,font=fonts[42],fill='#15273d');pos+=60
    pos+=18
    for key,lines in rows:
        d.text((70,pos),key,font=fonts[26],fill='#64748b')
        for j,line in enumerate(lines):d.text((290,pos+j*44),line,font=fonts[30],fill='#15273d')
        pos+=max(62,len(lines)*44+22)
    d.line((70,pos+8,930,pos+8),fill='#dce5ef',width=2)
    d.text((70,pos+26),'官方确认时间不单独作为二次上线证明',font=fonts[22],fill='#64748b')
    d.text((70,pos+61),'采集：'+row.get('snapshot','未提供'),font=fonts[22],fill='#64748b')
    d.text((70,pos+96),'运营商资费提醒 · 办理以官方公示为准',font=fonts[22],fill=color)
    out=io.BytesIO();canvas.save(out,format='JPEG',quality=90,optimize=True)
    content=out.getvalue()
    if len(content)>2*1024*1024:raise RuntimeError('资费图片超过企业微信2MB限制')
    return content
