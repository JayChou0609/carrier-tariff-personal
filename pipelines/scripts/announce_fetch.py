#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公告抓取脚本：江苏移动公告 + 联通公告，各只保留最新 15 条，输出 announce.json

用法:
    python3 pipelines/scripts/announce_fetch.py --move-dir data --uni-dir unicom/data
    （路径相对仓库根目录；前端读取的就是 data/announce.json 与 unicom/data/announce.json）
说明:
    - 移动(江苏)公告列表/详情均为静态 JSON，GET 直取；
      详情接口触发 TLS legacy renegotiation，需注入 openssl_legacy.cnf(见下)。
    - 联通公告列表/详情为 POST 接口，需带 XHR 特征头(否则中文被替换成 ?)。
    - 输出文件:
        <move-dir>/announce.json  移动站公告数据
        <uni-dir>/announce.json   联通站公告数据
"""
import os
import re
import json
import sys
import time
import datetime

# 源站(移动网关) TLS legacy renegotiation 兼容(与 main.py 同款处理)
_SSL_CNF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mobile", "openssl_legacy.cnf")
if os.path.exists(_SSL_CNF):
    os.environ.setdefault("OPENSSL_CONF", _SSL_CNF)

import urllib.request
import urllib.parse

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
MAX_KEEP = 15

# ---------------- 移动(江苏) ----------------
# 江苏官方列表页 index_250_250.html 声明的栏目 JSON。
MOVE_LIST_URL = ("https://www.10086.cn/aboutus/news/pannounce/js/250/5004505_873_2361.json")
MOVE_DETAIL_PREFIX = ("https://www.10086.cn/aboutus/news/pannounce/js/250/5004505_873_2361_detail_")
MOVE_DETAIL_PAGE = ("https://www.10086.cn/aboutus/news/pannounce/js/index_250_250_detail_{id}.html")
MOVE_SITE = "https://www.10086.cn"

# ---------------- 联通 ----------------
UNI_LIST_URL = "https://www.10010.com/mall/service/query/announcementquery"
UNI_DETAIL_URL = "https://www.10010.com/mall/service/query/announcementquerydetail"
UNI_PROVINCE = "034"  # 江苏；075 为江西
UNI_DETAIL_PAGE = ("https://www.10010.com/wt_links/index.html#/announcementDetail?announcementId={id}"
                   "&pageSize=12&pageNo=1")
UNI_IMG_HOST = "https://m1.img.10010.com"

UNI_HDRS = {
    "User-Agent": UA,
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Referer": "https://www.10010.com/wt_links/index.html",
    "Origin": "https://www.10010.com",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# 富文本中需要保留的基础标签
KEEP_TAGS = {"p", "br", "div", "span", "a", "img", "strong", "b", "em", "i", "u",
             "ul", "ol", "li", "table", "tr", "td", "th", "tbody", "thead", "h1",
             "h2", "h3", "h4", "blockquote"}


def _http_get(url, headers=None, timeout=30):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")


def _http_post(url, form, headers=None, timeout=30):
    data = urllib.parse.urlencode(form).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers=headers or {"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")


def strip_style(html):
    """去掉富文本中的 mso-*/font-* 等内联样式，保留 color / background / 基础的排版值"""
    def _fix(m):
        attrs = m.group(1)
        keep = []
        for kv in re.findall(r'([\w-]+)\s*:\s*([^;]+);?', attrs):
            k, v = kv[0].strip().lower(), kv[1].strip()
            if not k or not v:
                continue
            lower = (k + ":" + v.lower())
            if k in ("color", "vertical-align", "text-align", "background-color"):
                keep.append(f"{k}:{v}")
            elif v.startswith("#") and k.startswith("backg"):
                keep.append(f"{k}:{v}")
            elif k.startswith("background") and len(v) > 4:
                keep.append(f"{k}:{v}")
        return ' style="' + ";".join(keep) + '"' if keep else ""
    return re.sub(r'\sstyle="([^"]*)"', _fix, html)


def _safe_proto(url):
    """协议白名单：只放行 http/https/mailto 与相对链接，其余(javascript:/data: 等)置空。

    防止抓来的公告正文里夹带 javascript: 或 data:text/html 造成 XSS。
    """
    if not url:
        return ""
    u = str(url).strip()
    # 相对链接 / 锚点 / 站内路径：直接放行
    if u.startswith(("/", "#", "./", "../")):
        return u
    low = u.lower()
    for ok in ("http://", "https://", "mailto:"):
        if low.startswith(ok):
            return u
    return ""


def clean_html(raw, kind="move"):
    """Allowlist rich text and attributes; resolve links against the correct operator."""
    from html.parser import HTMLParser
    from html import escape

    class Cleaner(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.out, self.blocked = [], 0

        def handle_starttag(self, tag, attrs):
            if tag in {"script", "style", "iframe", "object"}:
                self.blocked += 1
                return
            if self.blocked or tag not in KEEP_TAGS:
                return
            kept = []
            for key, value in attrs:
                value = value or ""
                if (tag == "a" and key == "href") or (tag == "img" and key == "src"):
                    value = _safe_proto(value)
                    if value:
                        kept.append((key, _abs_link(value, kind)))
                elif key in {"title", "alt"} or (tag in {"td", "th"} and key in {"colspan", "rowspan"} and value.isdigit()):
                    kept.append((key, value))
            if tag == "a":
                kept.extend([("target", "_blank"), ("rel", "noopener noreferrer")])
            self.out.append("<" + tag + "".join(' %s="%s"' % (k, escape(v, quote=True)) for k, v in kept) + ">")

        def handle_endtag(self, tag):
            if tag in {"script", "style", "iframe", "object"}:
                self.blocked = max(0, self.blocked - 1)
            elif not self.blocked and tag in KEEP_TAGS and tag not in {"img", "br"}:
                self.out.append("</" + tag + ">")

        def handle_data(self, text):
            if not self.blocked:
                self.out.append(escape(text))

    parser = Cleaner()
    parser.feed(raw or "")
    return "".join(parser.out).strip()


def _abs_link(path, kind):
    base = MOVE_DETAIL_PAGE.format(id="") if kind == "move" else UNI_IMG_HOST + "/"
    return urllib.parse.urljoin(base, path)


def html_to_text(h):
    """提取富文本纯文本(用于摘要)"""
    t = re.sub(r"<br\s*/?>", "\n", h, flags=re.I)
    t = re.sub(r"</(p|div|tr|li|h\d)>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = htmlmod_unescape(t)
    return re.sub(r"\s+", " ", t).strip()


def htmlmod_unescape(s):
    import html as _h
    return _h.unescape(s)


def find_attachments(content_html, site):
    """从正文中提取附件(下载链接)"""
    out = []
    for m in re.finditer(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', content_html, flags=re.S | re.I):
        href, name_raw = m.group(1), m.group(2)
        if "/uploadBaseDir/" in href or re.search(r'\.(xlsx?|pdf|docx?|zip|rar|png|jpg|jpeg)(\?|$)', href, flags=re.I):
            name = html_to_text(name_raw).strip() or os.path.basename(href.split("?")[0]) or "附件"
            link = href if href.startswith("http") else (site + href)
            if link not in [a["url"] for a in out]:
                out.append({"name": name[:60], "url": link})
    return out


def now_str():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")


# ---------------- 移动抓取 ----------------
def fetch_move():
    print("[移动] 拉取公告列表 ...")
    raw = _http_get(MOVE_LIST_URL)
    j = json.loads(raw)
    lst = j["cData"]["list"] or []
    if not isinstance(lst, list) or not lst:
        raise ValueError("江苏移动公告列表为空或结构异常")
    items = []
    for row in lst:
        href = row.get("detail_href") or ""
        mid = None
        m = re.search(r"_detail_(\d+)\.", href)
        if m:
            mid = m.group(1)
        if mid is None:
            continue
        items.append({
            "id": mid,
            "title": row.get("noticeTitle") or "",
            "date": row.get("publishTime") or "",
            "page_url": MOVE_DETAIL_PAGE.format(id=mid),
        })
    items.sort(key=lambda x: x["date"], reverse=True)
    items = items[:MAX_KEEP]
    print(f"[移动] 列表 {len(lst)} 条，取最新 {len(items)} 条")
    for it in items:
        try:
            dj = json.loads(_http_get(MOVE_DETAIL_PREFIX + it["id"] + ".json"))
            c = dj.get("cData", {}).get("content", {})
            text = c.get("text") or ""
            content = clean_html(text)
            it["summary"] = html_to_text(content)[:120]
            it["content"] = content
            it["attachments"] = find_attachments(content, MOVE_SITE)
        except Exception as e:
            print(f"[移动] 详情 {it['id']} 失败: {e}")
            it["summary"], it["content"], it["attachments"] = "", "", []
        # 避免请求过快
        time.sleep(0.4)
    return items


# ---------------- 联通抓取 ----------------
def fetch_uni():
    print("[联通] 拉取公告列表 ...")
    lst = []
    page, total_pages = 1, 1
    while page <= total_pages:
        j = json.loads(_http_post(UNI_LIST_URL, {
            "pageNo": str(page), "pageSize": "20", "province": UNI_PROVINCE,
            "condition": "0", "title": ""}, UNI_HDRS))
        rows = j.get("result")
        if not isinstance(rows, list) or not rows:
            raise ValueError("江苏联通公告分页为空或结构异常")
        total_pages = int(j.get("totalPages", 1))
        if not 1 <= total_pages <= 100:
            raise ValueError("江苏联通公告分页数量异常")
        lst.extend(rows)
        page += 1
        time.sleep(0.2)
    items = []
    seen = set()
    for row in lst:
        if row.get("creatorProvinceName") != "江苏" or row.get("id") in seen:
            continue
        seen.add(row.get("id"))
        items.append({
            "id": row.get("id") or "",
            "title": row.get("title") or "",
            "date": (row.get("publishTime") or "")[:10],
            "page_url": UNI_DETAIL_PAGE.format(id=row.get("id") or ""),
        })
    items = [x for x in items if x["id"]]
    # 联通接口按「官方置顶顺序」返回（会将多年前的公告置顶，如 2015 年那条），
    # 并非时间倒序；先按发布时间排序再取前 MAX_KEEP 条，否则旧置顶公告会挤掉
    # 真正的近期公告，且展示顺序看起来像抓到了陈年数据。
    items.sort(key=lambda x: x.get("date") or "", reverse=True)
    items = items[:MAX_KEEP]
    print(f"[联通] 列表 {len(lst)} 条，取最新 {len(items)} 条")
    for it in items:
        try:
            dj = json.loads(_http_post(UNI_DETAIL_URL, {
                "announcementId": it["id"], "pageSize": "12", "pageNo": "1",
                "province": UNI_PROVINCE}, UNI_HDRS))
            n = dj.get("tNoticeDto") or {}
            text = n.get("noticeDetails") or ""
            content = clean_html(text, "uni")
            content = re.sub(r'(<img[^>]*?src=)["\'](?!https?://)([^"\']*)["\']',
                             lambda m: m.group(1) + '"' + UNI_IMG_HOST + m.group(2) + '"', content, flags=re.I)
            # Detail endpoint sometimes replaces Chinese metadata with question marks.
            # The list title is intact and authoritative; keep it.
            if not n or not text:
                raise ValueError("公告详情缺少正文")
            it["date"] = (n.get("noticeTime") or it["date"])[:10]
            it["summary"] = html_to_text(content)[:120]
            it["content"] = content
            it["attachments"] = find_attachments(content, UNI_IMG_HOST)
            for annex in n.get("annexInfos") or []:
                url = _safe_proto(annex.get("enclosureUrl"))
                if url:
                    name = annex.get("enclosureName") or ""
                    if not name or "?" in name:
                        name = urllib.parse.urlparse(url).path.rsplit("/", 1)[-1] or "附件"
                    if url not in [a["url"] for a in it["attachments"]]:
                        it["attachments"].append({"name": name, "url": url})
        except Exception as e:
            print(f"[联通] 详情 {it['id']} 失败: {e}")
            it["summary"], it["content"], it["attachments"] = "", "", []
        time.sleep(0.4)
    # 详情返回的 noticeTime 会覆盖列表里的发布日期，按最终日期再排一次，
    # 保证页面展示严格为时间倒序（最新公告在最前）。
    items.sort(key=lambda x: x.get("date") or "", reverse=True)
    if not items:
        raise ValueError("未取得有效的江苏联通公告")
    return items


def write_json(items, path, operator="mobile", status="ok", error=""):
    """Atomically persist a province-labelled feed; never relabel an old province cache."""
    old = {}
    try:
        with open(path, encoding="utf-8") as f:
            old = json.load(f)
    except (OSError, ValueError):
        pass
    compatible = old.get("province") == "jiangsu" and old.get("operator") == operator
    if status == "ok" and not items:
        raise ValueError("拒绝以空列表覆盖公告")
    if status != "ok":
        items = old.get("items", []) if compatible else []
    elif compatible:
        previous = {it["id"]: it for it in old.get("items", [])}
        for item in items:
            if not item.get("content") and previous.get(item["id"], {}).get("content"):
                item.update({k: previous[item["id"]][k] for k in ("content", "summary", "attachments")})
    data = {"province": "jiangsu", "province_name": "江苏", "operator": operator,
            "source_url": "https://www.10086.cn/aboutus/news/pannounce/js/index_250_250.html" if operator == "mobile" else "https://www.10010.com/wt_links/index.html#/announcement",
            "updated": now_str() if status == "ok" else old.get("updated", "") if compatible else "",
            "checked_at": now_str(), "status": status, "error": error,
            "count": len(items), "items": items}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    print(f"已写入 {path} ({len(items)} 条, {status})")


def _resolve(root, p):
    return p if os.path.isabs(p) else os.path.join(root, p)


def main():
    # 相对路径基准 = 仓库根目录（--move-dir data / --uni-dir unicom/data 直接对应站点读取位置）。
    # 此前基准是 pipelines/，workflow 传的 site/data、unicom/data 被解析成
    # pipelines/site/data、pipelines/unicom/data —— 与前端实际读取的根目录 data/、
    # unicom/data/ 不一致，导致公告文件写到了镜像位置、线上长期不更新。
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    args = sys.argv[1:]
    move_dir = uni_dir = None
    for i, a in enumerate(args):
        if a == "--move-dir" and i + 1 < len(args):
            move_dir = _resolve(root, args[i + 1])
        if a == "--uni-dir" and i + 1 < len(args):
            uni_dir = _resolve(root, args[i + 1])
    failed = False
    for directory, fetcher, operator in [(move_dir, fetch_move, "mobile"), (uni_dir, fetch_uni, "unicom")]:
        if not directory:
            continue
        path = os.path.join(directory, "announce.json")
        try:
            write_json(fetcher(), path, operator)
        except Exception as exc:
            failed = True
            print(f"[{operator}] 公告采集失败，保留江苏旧数据: {exc}", file=sys.stderr)
            write_json([], path, operator, "failed", str(exc)[:200])
    if not move_dir and not uni_dir:
        print(__doc__)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
