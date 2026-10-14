# Google 字体外链本地化（消除前端资产包的阻塞式 `@import`）

> **状态**：`已上线` ｜ **主题**：`Google 字体本地化` ｜ **取代**：`—` ｜ **核对**：`2026-09-28`

> **结论（先看这条）**：站点前端资产包 `web.assets_frontend.min.css` **第 1 行**那条阻塞式
> `@import url("https://fonts.googleapis.com/css?family=Roboto:…")` 已**在本机克隆与生产上**换成**本地**
> `/web/content/<id>/google-font-Roboto`。做法**不是改代码**，而是调用 Odoo 自带的服务端方法
> `env['website.assets'].make_scss_customization(...)`，把 Roboto 落成 `ir.attachment`；
> 同一个确定性屏蔽条件下，`DOMContentLoaded` 从 **3/3 30s 未到达** 变为 **3/3 0.12–0.30s 到达、对外网 0 次请求**。
> **已于 2026-09-28 上生产**（状态 = 已上线；生产**自己的**附件 id = `1317`，**未沿用**本机 2449/2512/2570 —— 本机每次重跑都会变）。
> 生产命令原文、原始输出与逐项验收见 **§10**；§7 步骤书保留原文，其中 3 处会导致执行失败的写法已就地标出并回写。

> **纪律提醒**：本文 §1–§6 与 §8 的数字都来自**本地克隆** `edu19`（容器 `edu19-clone-web-1` / `edu19-clone-db-1`）。
> 每处测量都申报了当时的**并发浏览器进程数**（见 §5），因为本机同时有多会话在跑浏览器门禁，
> **并发会把计时打脏**（已实测：并发下"健康网络"对照组 3 次里 2 次假超时）。

---

## 1. 为什么（问题是什么）

### 1.1 现场证据（改前）

```
$ curl -s "http://localhost:8069/" | grep -o 'href="[^"]*web.assets_frontend.min.css"'
href="/web/assets/1/0bfd426/web.assets_frontend.min.css"

$ curl -s -o /tmp/asset_before.css -w "HTTP %{http_code} bytes=%{size_download}\n" \
    "http://localhost:8069/web/assets/1/0bfd426/web.assets_frontend.min.css"
HTTP 200 bytes=1204980

$ head -1 /tmp/asset_before.css
@import url("https://fonts.googleapis.com/css?family=Roboto:300,300i,400,400i,700,700i&display=swap");
```

即**每一个前端页面**（1.2 MB 的资产包）都带着一条指向 `fonts.googleapis.com` 的 `@import`。

### 1.2 它为什么是"阻塞式"

`@import` 写在样式表内部：CSSOM 就绪要等这条外链；而**经典 `<script>` 的执行必须等它前面的样式表就绪**，
所以这条外链会把 `DOMContentLoaded` 一起拖住。实测（§5）证实了这条因果 —— 屏蔽 Google 后页面**根本到不了 DCL**。

### 1.3 实测：屏蔽 Google 后页面到不了 `DOMContentLoaded`

探针：`http://localhost:8069/`，`wait_until="domcontentloaded"`，上限 30 s，n=3，视口 1280×800，
在网络层把 `fonts.googleapis.com` + `fonts.gstatic.com` **黑洞**（route handler 不 resolve ⇒ 请求一直挂着）：

| 状态 | 结果 | 对外请求计数 |
|---|---|---|
| 改前 | **3/3 `timeout/未到达`**（`TimeoutError: Page.goto: Timeout 30000ms exceeded`） | `google_requests=1` |
| 改后 | **3/3 到达**，`0.122–0.295 s` | **`google_requests=0`** |

`google_requests=1` 是关键细节：页面**已经走到 CSS 解析**、正卡在那条 `@import` 上，
不是"整站打不开"。`google_requests=0` 则说明改后**对外网一次请求都不发**。

### 1.4 必须说清的一句话：**本机无法如实复现"中国网络"**

本机 Chromium **能连上 Google**，用最小页 + CDP 原始事件验证过（`<link rel="stylesheet"` 指向
`https://fonts.googleapis.com/css?family=Roboto`，Playwright 默认无 `--proxy-server`）：

```
6/6 run：Network.requestWillBeSent → Network.responseReceived HTTP 200 → Network.loadingFinished bytes≈1985
无 PENDING、无 loadingFailed
```

所以上面的**黑洞是"中国网络不可达"的替身，不是它本身**。凡本文出现"屏蔽 / 黑洞"，
都应读作"在确定性条件下让这两个域名不可达"，**不要**读成"我们在真实中国网络里测过"。
（附带一条教训：本机同时跑多会话时，"健康网络"对照组会假超时 —— 我第一版据此错误怀疑过
"Chromium 连不上 Google"，安静窗口重测即 3/3 到达 1.007 / 1.076 / 2.485 s，怀疑被推翻。）

---

## 2. 这条 Roboto 是从哪来的（不是 website 模块默认值）

Odoo 19 网站默认字体是 `Inter` / `Inter Tight`（`website/static/src/scss/primary_variables.scss` 的
`$o-website-values-palettes`）。本仓这条 Roboto 来自**主题**：

```
openeducat_erp/theme_web_openeducat/static/src/scss/primary_variables.scss:8-11
        'font':                             'Roboto',
        'headings-font':                    'Roboto',
        'navbar-font':                      'Roboto',
        'buttons-font':                     'Roboto',
```

四个 alias（base / headings / navbar / buttons）**各发一条 `@import`** —— 这解释了为什么改后
CSS 里本地 import 有 **4 条一模一样的 URL**（`website.scss` 的 `$-seen-urls` 去重只在**远程**分支生效，
本地分支不记入 `$-seen-urls`）。URL 相同，浏览器自动去重，纯冗余、无功能影响。

---

## 3. 怎么修的（服务端调用链，不需要 GUI、不需要管理员登录）

### 3.1 入口

```python
env['website.assets'].make_scss_customization(
    '/website/static/src/scss/options/user_values.scss',
    {'google-local-fonts': "('Roboto': '')"})
```

**`'Roboto': ''`（空值）就是"请下载"的暗号**，不是笔误。取值来源于 UI 同款触发点：

```js
// website/static/src/builder/plugins/font/add_font_dialog.js:317
this.props.googleLocalFonts.push(\`'\${font}': ''\`);
```

服务端读同一个键时按"值是否为空"分派（`website/models/assets.py:235-294`）：
**空值 ⇒ 现在就去 Google 抓**；**带 id（`'Roboto': 12`）⇒ 已经本地化过了，直接用**。

### 3.2 链路

| 环节 | 位置 | 作用 |
|---|---|---|
| 下载 + 建附件 | `website/models/assets.py:235-294`（`google_local_fonts` 分支） | 抓 Google CSS，把每个 `src: url(...)` 改写成 `/web/content/<id>/<name>`，落 `ir.attachment` |
| 写回定制值 | 同方法尾部 `save_asset` | 把 `('Roboto': <主 CSS 附件 id>)` 写进自定义 `user_values.scss` |
| 决定发远程还是本地 | `website/static/src/scss/website.scss:6-16` | `$-url` 有值 ⇒ 发 Google；否则看 `$-attachment` ⇒ 发 `/web/content/...` |
| 把本地字体并进字体表 | `website/.../secondary_variables.scss:238-247` | `map-remove` 掉带 `url` 的 Roboto，换成带 `attachment` + `name` 的条目 |

### 3.3 产出（本地库终态）

| 项 | 改前 | 改后 |
|---|---|---|
| bundle URL | `/web/assets/1/`**`0bfd426`**`/web.assets_frontend.min.css` | `/web/assets/1/`**`78ed718`**`/web.assets_frontend.min.css` |
| 字节 | 1,204,980 | 1,205,132 |
| `fonts.googleapis.com` 命中 | 1 | **0** |
| `@import` | `https://fonts.googleapis.com/css?family=Roboto:…` | `/web/content/2570/google-font-Roboto` ×4 |
| `ir_attachment name LIKE 'google-font%'` | **0** | **54** |
| `ir_attachment name LIKE '%(google-font)%'` | 0 | 1（`Roboto (google-font)`，33156 B，`text/css`） |
| `user_values.scss` | 无该键 | `'google-local-fonts': ('Roboto': 2570),` |

> **54 与 55 不是矛盾，是两种口径**（原写法 → 为什么错 → 正确写法）：
>
> · **原写法**：本表用原始 SQL `LIKE 'google-font%'` 记 **54**；而 §7 第 2 步脚本用 ORM
>   `search_count([('name', 'like', 'google-font%')])` 打印 **55**。同一天、同一个库，两个数字并存。
> · **为什么错**：Odoo ORM 的 `like` 是**包含**语义（编译成 `LIKE '%<值>%'`），所以 `'google-font%'`
>   还会额外命中 `Roboto (google-font)`；而 psql 里手写的 `LIKE 'google-font%'` 是**前缀**匹配，不命中它。
>   ⇒ ORM 的 55 **不是多算了一条**，是两把尺子量同一堆东西。
> · **正确写法**：报数必须写明口径 —— **54 个 woff2**（`LIKE 'google-font%'` 前缀匹配）
>   **+ 1 个主 CSS**（`Roboto (google-font)`，`LIKE '%(google-font)%'`）**= 55 条新建附件**。
>   生产实测同为 54 + 1 = 55（§10.4）。

**字体字节与 Google 现下载完全一致** ⇒ 排版度量不可能变（这也是 §5 A 轴零变化的原因）：

```
stored sha256: d8d0c88eea1036dc3e7322cd0a1a3eb6fc1dd86da24c7de690e70aac1bd62f05
fresh  sha256: d8d0c88eea1036dc3e7322cd0a1a3eb6fc1dd86da24c7de690e70aac1bd62f05
```

---

## 4. 最大的坑：`odoo shell` 不会调 `signal_changes()`

**症状**：DB 已经改对了（附件齐全、`user_values.scss` 也写好了），但 curl 首页拿到的
**还是旧 bundle**（URL 都没变、`@import` 照旧）—— 6 个 worker 里每个都缓存着旧结果。

**机制**：`env.registry.clear_cache('assets')` **只在本进程打标记**；
真正让它对其他进程生效的是 `signal_changes()` —— 它往 `orm_signaling_assets` **插一行**，
其他 worker 下次请求时 `check_signaling()` 发现序号变了才清缓存
（`odoo/orm/registry.py:998` clear_cache / `:1103` check_signaling / `:1139` signal_changes）。
而 `signal_changes()` 是 **WSGI worker 在请求结束时**调的，**`odoo shell` 从不调**。

**修法**（生产同样适用，**因此不需要重启容器、不需要停机**）：

```python
env.registry.clear_cache('assets')
env.registry.signal_changes()
env.cr.commit()
```

**实测**：补这一句后 `orm_signaling_assets` 的 `max(id)` 由 **3 → 4**，bundle URL 立刻从
`0bfd426` 变为 `6e9f36d`，`fonts.googleapis.com` 命中归 0。

---

## 5. 效果数字（before / after）

探针口径见 §1.3；**每组都申报并发状态**。

| 条件 | 改前 | 改后 |
|---|---|---|
| **黑洞屏蔽 Google**（n=3） | 3/3 `timeout/未到达`（`google_requests=1`） | 3/3 到达 `0.122–0.295 s`，**`google_requests=0`** |
| 无屏蔽（健康网络，n=3） | 1.007 / 1.076 / 2.485 s | 0.085 / 0.096 / 0.136 s |

**并发申报**：改前那组 10:28:05 起测、10:29:42 结束，**前后 `browser_procs` 皆为 0（干净）**；
改后那组起测时 `browser_procs=7`（另一会话在跑）⇒ **该组并发 = busy**。
但主指标 `google_requests=0` **与负载无关**（负载只会让它更慢、不会伪造出依赖），故结论成立，
只有 wall-clock 应读作**上界**。

### 5.1 A 轴回归（`scripts/check_ui_usability.py --report`）

| 读数 | 采集时刻 | 并发 | A | B | C | D |
|---|---|---|---|---|---|---|
| `usability-baseline.json` | 09:40:31 | quiet | 0 | 0 | 0 | 0 |
| `usability-20260928-1005.json` | 10:03:16 | quiet | 0 | 0 | 0 | 0 |
| `usability-20260928-1037.json`（改后） | 10:35:17 | busy | 0 | 0 | 0 | 0 |
| `usability-20260928-1046.json`（改后 · 权威） | 10:45:04 | **quiet** | **0** | 0 | 0 | 0 |

改后权威那一份：`探页 143 条 = 97 页 × 身份；探到 139 ｜ 非环境失败 0`，
`并发 quiet`、`样本有效=True`。**A 轴 0 条、无新增无恶化，没有需要点名的页面** ——
与 §3.3"字体字节 sha256 相同"互为旁证：字体本身没换，只换了交付路径。

> 注：两份「改后」读数采集时本地字体 id 是 `2512`；本文最终态是 `2570`（§3.3，验证过程中回滚重跑过一次）。两者字体字节相同、CSS 只差 URL 里的数字，**A 轴不受影响**。

---

## 6. 持久性与回滚（都实测过）

### 6.1 持久性：升级 / 重建资产 / 清缓存都打不回原形

在**隔离克隆**上做（不污染共享库）：`pg_dump` 本地库（126 MB）→ 新库 `edu19_fonttest`
+ filestore 副本 → `odoo -d edu19_fonttest -u website --stop-after-init` ⇒ **rc=0、无真 ERROR 级日志**
（`grep -ci "ERROR|CRITICAL|Traceback"` 曾报 31 行，**逐行核对后是大小写误匹配**：
真实内容为 WARNING `Error-prone use of @class …` 与 `View error context:`；区分大小写后为 **0 行**）。

升级后：附件 796 **checksum 不变**、`ir_asset 102 (directive=replace)` 仍在、54 条字体附件仍在；
把克隆起在 8099 端口抓包 ⇒ 仍然 `googleapis = 0`、本地 `/web/content` import 4 条。用完 **drop 掉克隆**。

另在活库上做"删掉生成的 bundle 附件 + 发失效信号"⇒ 重新生成后 URL 不变、仍 0 命中。

**机制上的理由**：本地化状态存在 `ir_asset` + `ir_attachment` 这类**非模块数据**行里
（实测二者都没有 `ir_model_data` 记录），`-u` 只重写自己 `xml_id` 名下的行 ⇒ 打不回原形。

### 6.2 回滚：用 Odoo 官方逆操作，不手改文件

```python
A.make_scss_customization(url, {'delete-font-attachment-id': aid,   # 主 CSS 附件 id
                                'google-local-fonts': 'null'})
```

对应 `website/models/assets.py:226-234` 的 `delete-font-attachment-id` 分支。
**实测结果**：`'google-local-fonts': null`、**55 条字体附件全部删除（0 行）**、
服务 CSS 回到远程 `@import url("https://fonts.googleapis.com/…Roboto…")`。
回滚后已重新应用，本地终态 = 已本地化。

---

## 7. 生产执行步骤（**已于 2026-09-28 在生产执行**；执行结果见 §10。以下保留执行书原文，并就地标出 3 处会导致失败的写法）

> 生产：SSH 别名 `prod-host`（连接可能超时，**要重试**），容器 `edu19-prod-web-1` / `edu19-prod-db-1`，库 `edu19`。
> **前提：本步骤书只在"生产上没有正在进行的部署"时执行** —— 与其它部署并行会让两边的验证互相盖住。

### 第 0 步 · 前置闸门（任一不过就停）

```bash
ssh prod-host '
  docker ps --format "{{.Names}}\t{{.Status}}" | grep prod
  docker exec edu19-prod-db-1 pg_dump -U odoo -d edu19 -Fc -f /tmp/edu19_pre_font.dump
  docker exec edu19-prod-db-1 ls -la /tmp/edu19_pre_font.dump
  docker exec edu19-prod-web-1 du -sh /var/lib/odoo/filestore/edu19
  echo "--- 改前基线（判据：google-font% = 0，且 CSS 里 fonts.googleapis.com ≥ 1）---"
  docker exec edu19-prod-db-1 psql -U odoo -d edu19 -tAc \
  # 表名是 ir_attachment（ir.attachment 是模型名，不是表名）—— 见下方「已修正的原写法」
    "SELECT count(*) FROM ir_attachment WHERE name LIKE '"'"'google-font%'"'"';"
  U=$(curl -s http://localhost:8069/ | grep -oE "href=\"[^\"]*web.assets_frontend.min.css\"" | sed "s/href=\"//;s/\"//")
  echo "bundle=$U"
  curl -s "http://localhost:8069$U" | grep -c "fonts.googleapis.com"
'
```

**验收判据**：dump 存在且 > 1 MB；`google-font%` 计数 **= 0**（如果已经 > 0，说明这台机器已经本地化过，
先去 §6.1 核对，**不要盲目重跑**）；`fonts.googleapis.com` 命中 **≥ 1**（若 = 0，说明当前根本没有远程依赖，
**停下来**，别做无谓改动）。
> **⚠ 已修正的原写法（2026-09-28 生产实测）** —— 照原文抄会**一条判据都取不到数**：
> · **原写法**：`SELECT count(*) FROM ir.attachment WHERE name LIKE 'google-font%';`
> · **为什么错**：`ir.attachment` 是 **Odoo 模型名，不是数据库表名**。生产 psql 实测
>   `ERROR:  relation "ir.attachment" does not exist`；旁证 `SELECT to_regclass('ir.attachment');`
>   返回**空行**，而 `SELECT to_regclass('ir_attachment');` → `ir_attachment`。
> · **正确写法**：`SELECT count(*) FROM ir_attachment WHERE name LIKE 'google-font%';`（第 3 步同样改）。

### 第 1 步 · 出网闸门：**不通就停，不要试备用方案**

A 方案的字体是**从 Google 现下载**的，所以生产机必须能连**两个**域名。任何一个不通 ⇒ **停止**：

```bash
ssh prod-host 'docker exec edu19-prod-web-1 bash -lc "
  UA=\"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/101.0.4951.41 Safari/537.36\"
  curl -sS -A \"\$UA\" -o /dev/null -w \"googleapis: %{http_code}\n\" --max-time 20 \
    \"https://fonts.googleapis.com/css?family=Roboto:300,300i,400,400i,700,700i&display=swap\"
  curl -sS -A \"\$UA\" -o /dev/null -w \"gstatic:   %{http_code}\n\" --max-time 20 \
    \"https://fonts.gstatic.com/s/roboto/v51/KFO5CnqEu92Fr1Mu53ZEC9_Vu3r1gIhOszmkC3kaWzU.woff2\"
"'
```

**验收判据：两行都必须是 `200`。**
**任何一个不是 200 ⇒ 立即停止，不要执行第 2 步。** 本文**不提供**"连不上 Google 时怎么办"的备用方案 ——
那条路（异地下载字体后导入附件）**我未验证**，写出来只会让人照着踩坑。连不上时请回到设计阶段重新选型
（例如改用系统字体栈，见 §8 的 B 方案说明）。

### 第 2 步 · 执行本地化（脚本原文，可直接落盘到生产主机）

把下面内容存成生产主机上的 `/tmp/localize_fonts.py`（**与本地实测执行过的脚本逐字相同** —— 2026-09-28 在本地克隆 `edu19` 上「先回滚、再执行本脚本」整套跑通：回滚把 55 条附件全删、CSS 回到远程 @import；本脚本 82.9s 抓到 55 个文件（1 次重试）、googleapis 归 0、失效信号序号 7 变 9），再喂给 `odoo shell`：

```python
import base64, re, time
import requests as _rq

url = '/website/static/src/scss/options/user_values.scss'
A = env['website.assets']

# --- STEP 0: derive the remote families actually emitted by the CURRENT bundle (not hardcoded) ---
bundle = env['ir.attachment'].search([('name', '=', 'web.assets_frontend.min.css')], order='id desc', limit=1)
if not bundle:
    print('ABORT: bundle attachment not found'); raise Exception('ABORT')
css = base64.b64decode(bundle.datas).decode('utf-8', 'replace')
fams = sorted(set(re.findall(r'fonts\.googleapis\.com/css\?family=([^&"\)\x27]+)', css)))
names = []
for f in fams:
    n = f.split(':')[0].replace('+', ' ')
    if n and n not in names:
        names.append(n)
print('STEP0 bundle=%s bytes=%d' % (bundle.id, len(css)))
print('STEP0 remote @import family params =', fams)
print('STEP0 -> fonts to localize =', names)
if not names:
    print('STEP0: no remote @import -> nothing to do'); raise Exception('NOTHING_TO_DO')

# --- STEP 0b: harden the network only (Odoo core hardcodes timeout=5 per font file;
#     54 sequential fetches => one stall aborts everything). Same code path, retried. ---
_orig_get = _rq.get
_stats = {'n': 0, 'retries': 0}
def _patched_get(u, **kw):
    if 'fonts.gstatic.com' in u or 'fonts.googleapis.com' in u:
        _stats['n'] += 1
        kw['timeout'] = 30
        last = None
        for attempt in range(1, 6):
            try:
                r = _orig_get(u, **kw)
                if r.status_code == 200:
                    return r
                last = Exception('HTTP %s' % r.status_code)
            except Exception as e:
                last = e
            _stats['retries'] += 1
            time.sleep(1.0 * attempt)
        raise last
    return _orig_get(u, **kw)
_rq.get = _patched_get

# --- STEP 1: exactly what the website font editor sends (add_font_dialog.js:317) ---
values = {'google-local-fonts': '(' + ', '.join("'%s': ''" % n for n in names) + ')'}
print('STEP1 make_scss_customization(%r, %r)' % (url, values))
t0 = time.time()
A.make_scss_customization(url, values)
env.cr.commit()
print('STEP1 OK in %.1fs ; font fetches=%d retries=%d' % (time.time() - t0, _stats['n'], _stats['retries']))

# --- STEP 2: read back ---
att = A._get_custom_attachment(A._make_custom_asset_url(url, 'web.assets_frontend'))
txt = base64.b64decode(att.datas).decode()
print('STEP2 attachment', att.id, 'checksum', att.checksum)
print('STEP2 line ->', [l.strip() for l in txt.splitlines() if 'google-local-fonts' in l])
print('STEP2 count name like google-font%% :', env['ir.attachment'].search_count([('name', 'like', 'google-font%')]))
print('STEP2 main font-css attachment :', [(a.id, a.name, a.mimetype, a.file_size)
      for a in env['ir.attachment'].search([('name', 'like', '%(google-font)%')])])
print('STEP2 sample woff2 attachments :', [(a.id, a.name, a.file_size)
      for a in env['ir.attachment'].search([('name', 'like', 'google-font%')], limit=3)])

# ===== 第二段：发布跨进程失效 —— 本机实测执行过（/tmp/shell_signal.py）=====
# 少了这三行，6 个 worker 会继续发旧 bundle（DB 已改对也没用）—— 见报告 §4。
env.registry.clear_cache('assets')
env.registry.signal_changes()
env.cr.commit()
env.cr.execute("SELECT max(id) FROM orm_signaling_assets")
```

```bash
ssh prod-host 'docker cp /tmp/localize_fonts.py edu19-prod-web-1:/tmp/localize_fonts.py'
ssh prod-host 'docker exec -i edu19-prod-web-1 odoo shell -c /etc/odoo/odoo.conf \
  --db_host=db -r odoo -w odoo -d edu19 --no-http < /tmp/localize_fonts.py'
```

**验收判据**：输出含 `STEP0 -> fonts to localize = ['Roboto']`、`STEP1 OK in`（形如 `STEP1 OK in 82.9s ; font fetches=55 retries=1`）。**无 Traceback**；`echo $?` 应为 **0**。（若输出 `STEP0: no remote @import -> nothing to do` 并带 Traceback，说明**这台机器已经本地化过** —— 这是脚本的安全护栏，它不会写任何东西，去 §7 第 0 步看处置。）
耗时随机器负载波动很大（本机 93.5 s / 396 s 两次）⇒ **预留 2–8 分钟**，并挑机器空闲时跑。

### 第 3 步 · 三条硬判据（全过才算成功）

```bash
ssh prod-host '
  echo "--- (1) 附件计数：必须 > 0 ---"
  docker exec edu19-prod-db-1 psql -U odoo -d edu19 -tAc \
  # 表名是 ir_attachment（同第 0 步，见那处的「已修正的原写法」）
    "SELECT count(*) FROM ir_attachment WHERE name LIKE '"'"'google-font%'"'"';"
  echo "--- (2) 服务出的 CSS：googleapis 必须 = 0，且出现本地 /web/content ---"
  U=$(curl -s http://localhost:8069/ | grep -oE "href=\"[^\"]*web.assets_frontend.min.css\"" | sed "s/href=\"//;s/\"//")
  echo "bundle=$U"
  curl -s "http://localhost:8069$U" -o /tmp/after.css
  echo "googleapis = $(grep -c fonts.googleapis.com /tmp/after.css)"
  grep -o "@import url(\"/web/content/[^\"]*\")" /tmp/after.css | sort | uniq -c
  echo "--- (3) 本地字体链路可达 ---"
  ID=$(grep -o "/web/content/[0-9]*/google-font-Roboto" /tmp/after.css | head -1 | cut -d/ -f4)  # -f4 而不是 -f3，见下方「已修正的原写法」
  curl -s -o /dev/null -w "font css: HTTP %{http_code}\n" "http://localhost:8069/web/content/$ID/google-font-Roboto"
'
```

1. `google-font%` 计数 **> 0**；
2. `googleapis = 0` **且**至少 1 条 `/web/content/…`；
3. 本地字体 CSS **HTTP 200**。
> **⚠ 已修正的原写法（2026-09-28 生产实测）** —— 会让**判据 3 假红**：
> · **原写法**：`ID=$(grep -o "/web/content/[0-9]*/google-font-Roboto" /tmp/after.css | head -1 | cut -d/ -f3)`
> · **为什么错**：`grep -o` 的匹配串**以 `/` 开头**，按 `/` 切分后 `-f1` 是空串、`-f2=web`、
>   `-f3=content`、`-f4=<id>`。于是 `$ID` 恒等于字面量 **`content`**，拼出
>   `/web/content/content/google-font-Roboto` ⇒ **HTTP 404** ⇒ 判据 3 **必然假红**。
>   生产实测正是如此：原式 **404**，改 `-f4` 得 `1317` → **200**。
> · **正确写法**：`… | head -1 | cut -d/ -f4)` ⇒ 取到生产自己的 id（本次是 `1317`），链路 200。

> ⚠️ **绝不能沿用本地那个附件 id** —— 本机当前是 `2570`，而且**每次重跑都会变**（本次实测经历了 2449 → 2512 → 2570），那是本地库的行号，生产库的附件 id 必然不同。
> 一律用第 3 步从**生产自己**的 CSS 里现取（这正是脚本里 `ID=$(…)` 那行的用意）。
> 同理 `user_values.scss` 里也会写成生产自己的 id（形如 `'google-local-fonts': ('Roboto': <生产id>),`）。

### 第 4 步 · 回滚

（**与本地实测执行过的脚本逐字相同** —— 2026-09-28 实测结果：55 条字体附件全删（0 行）、服务 CSS 回到远程 `@import`。）

```python
import base64, re
url = '/website/static/src/scss/options/user_values.scss'
A = env['website.assets']
att = A._get_custom_attachment(A._make_custom_asset_url(url, 'web.assets_frontend'))
txt = base64.b64decode(att.datas).decode()
m = re.search(r"'google-local-fonts': \('([^']+)': (\d+)\)", txt)
print('ROLLBACK detected entry:', m.group(0) if m else None)
if not m:
    print('ROLLBACK: nothing to roll back'); raise Exception('NOTHING')
fam, aid = m.group(1), int(m.group(2))
before = env['ir.attachment'].search_count([('name', 'like', 'google-font%')])
print('ROLLBACK before: google-font%% attachments = %d, main css id = %d' % (before, aid))
# OFFICIAL inverse: website/models/assets.py:226-234 (delete-font-attachment-id) + google-local-fonts='null'
A.make_scss_customization(url, {'delete-font-attachment-id': aid, 'google-local-fonts': 'null'})
env.cr.commit()
env.registry.clear_cache('assets')
env.registry.signal_changes()
env.cr.commit()
txt2 = base64.b64decode(A._get_custom_attachment(A._make_custom_asset_url(url, 'web.assets_frontend')).datas).decode()
print('ROLLBACK after: line ->', [l.strip() for l in txt2.splitlines() if 'google-local-fonts' in l])
print('ROLLBACK after: google-font%% attachments =',
      env['ir.attachment'].search_count([('name', 'like', 'google-font%')]),
      '| %%(google-font)%% =', env['ir.attachment'].search_count([('name', 'like', '%(google-font)%')]))
print('ROLLBACK existing main css attachment still present?', env['ir.attachment'].browse(aid).exists())
```

```bash
ssh prod-host 'docker cp /tmp/rollback_fonts.py edu19-prod-web-1:/tmp/rollback_fonts.py'
ssh prod-host 'docker exec -i edu19-prod-web-1 odoo shell -c /etc/odoo/odoo.conf \
  --db_host=db -r odoo -w odoo -d edu19 --no-http < /tmp/rollback_fonts.py'
```

**验收判据**：`google-font%` 计数回到 **0**，且服务 CSS 里 `fonts.googleapis.com` 命中 **≥ 1**。
兜底：`pg_restore` 第 0 步的 dump（另需还原 filestore 副本）。

---

## 8. 遗留风险与不确定项

1. **A 方案硬依赖生产能连 Google**（`fonts.googleapis.com` **和** `fonts.gstatic.com` 都要通）。
   连不上时 **没有已验证的备用路径**（见 §7 第 1 步）—— 要另选型，别硬试。
2. **下载步骤天生脆**：core 每个字体文件硬编码 `timeout=5`、55 次串行抓取
   （本机实测第一次挂 1 次、第二次重试 9 次）。§7 第 2 步的加固**不是可选项**，并且要挑空闲窗口。
3. **残留一条非阻塞外链**：每页 `<head>` 里仍有
   `<link rel="preconnect" href="https://fonts.gstatic.com/" crossorigin>`
   （`website/views/website_templates.xml:175`）。它**不阻塞渲染**（失败即静默），
   A 与 B 方案**都不会**去掉它；要清掉需另加一条视图覆盖，属可选后续。
4. **编辑器专用残留**：`website.website_builder_assets.min.css`（附件 2382）仍有 **8 条**
   Google `@import`（字体选择器的预览名单：Arvo / Inter / Noto Serif / Open Sans / Poppins /
   Raleway / Roboto / Source Sans Pro）。已验证公网页 `/`、`/web/login`、`/contactus`
   对它**引用数 0** ⇒ 只影响进网站编辑器的人。**A 不修，B 也不修。**
5. `@import` 重复 4 条（每个 alias 一条）纯冗余，浏览器去重，无功能影响。
6. **度量口径是 `DOMContentLoaded`**，不是 LCP / 首屏绘制。阻塞机制本身已证实（§1.3），
   但**没有**测视觉完整时间。
7. **本机无法如实复现中国网络**（§1.4）⇒ 所有"屏蔽下"的结论都应读作"确定性屏蔽 Google 下"。
8. 本地库的 CLI 细节：容器只发布了 8069/8072，**未发布 8099**。验证隔离克隆时必须
   `docker exec` 进容器内 curl，主机侧 `curl localhost:8099` 必然失败。

### 8.1 B 方案（改用非 Google 字体）—— 仅调研，**本仓未实施**

- **改哪里**：改的是**站点字体值**，不是文件。它按站点存在自定义 `user_values.scss` 的
  `$o-user-website-values` 里（`font` / `headings-font` / `navbar-font` / `buttons-font`），
  UI 入口是网站编辑器 Theme 标签的字体选择器。Odoo 19 内置的**非 Google** 选项是 `SYSTEM_FONTS`
  （`website/static/src/scss/primary_variables.scss:2265-2273` 的 `$o-base-theme-font-configs`，
  UI 标签 "System Fonts"，见 `html_builder/static/src/plugins/font/font_plugin.js:122`）。
  它**只有 `'family'` 没有 `'url'`** ⇒ `website.scss` 的 `@if $-url` 为假 ⇒ **一条 `@import` 都不发**。
  服务端等价写法（**源码推断，未执行**）：
  ```python
  make_scss_customization(url, {'font': "'SYSTEM_FONTS'", 'headings-font': "'SYSTEM_FONTS'",
                                'navbar-font': "'SYSTEM_FONTS'", 'buttons-font': "'SYSTEM_FONTS'"})
  ```
- **代价**：字体栈变成 `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue",
  Ubuntu, "Noto Sans", Arial, sans-serif, …`（`web/static/src/scss/primary_variables.scss:30`）
  ⇒ macOS 显示 San Francisco、Windows 显示 Segoe UI、Android/Linux 仍是 Roboto（但来自系统、**不下载**）
  ⇒ **跨平台观感不再统一，品牌视觉会变**；中文渲染基本不受影响（中文字形本来就走系统字体栈）。
  好处是**完全不需要外网**，对"生产机连不上 Google"的场景比 A 更稳；副作用是 §8 第 3、4 条**依旧存在**。

---

## 9. 证据归属

- 本轮的 before/after 计时与网络层证据：探针脚本
  `/tmp/pw_font_probe.py`（黑洞 / abort / none 三模式）与 `/tmp/pw_google_reach.py`（CDP 原始事件）。
  两者都是**一次性探针**，未入库。
- **A 轴回归的两份读数 `tests/ui/readings/usability-20260928-1037.json` 与
  `usability-20260928-1046.json` 由本次修复产生**（`scripts/check_ui_usability.py --report` 落盘）。
  其中 `-1046` 是**权威样本**（采集时 `browser_procs` 前后皆 0、脚本自报 `并发 quiet`）。
  这两份文件被提交 **`dad6c06`**（2026-09-28 10:49:18，`feat(ui-gates): 给 /assess 三条补 route_matrix`）
  一并收录 —— **该提交的主题是 `/assess` 路由门禁补充，与本次字体修复无关**，只是同一次
  `git add` 的范围覆盖到了这两份读数；归属在此记明。
- `usability-baseline.json`（09:40）与 `usability-20260928-1005.json`（10:03）是**改前**读数，
  由并发会话产生，本次仅作对照引用。

## 10. 生产执行结果（2026-09-28）

> **终态 = 已本地化**。全程**未重启 web 容器**（§10.5）、无停机、无 commit。按 §7 顺序逐条执行；
> 第 2 步脚本**从本文正文逐字提取**（3304 B，sha256 `0dccfdd6fce54e400d87986e62df47eaffa30a1863f0a06bdeab660c0023cbf5`），未重打、未改写。

### 10.1 第 1 步 · 出网闸门（**真过**）

在 `edu19-prod-web-1` 内实测：

```
googleapis: 200      googleapis_curl_rc=0
gstatic:   200       gstatic_curl_rc=0
补充：实际抓 Google CSS = HTTP 200 bytes=33588，src: url( 共 54 条
```

### 10.2 备份

| 项 | 实测 |
|---|---|
| 执行书原版 dump（容器 `/tmp/edu19_pre_font.dump`，`-Fc`） | 9,453,738 B（> 1 MB 判据通过） |
| 用户要求路径 `/root/pre_font_20260928.gz`（`-Fp` 管道给 `gzip -9`） | **4,764,066 B**（非 0），`gzip -t` rc=0，含 `PostgreSQL database dump complete` |

### 10.3 第 2 步 · 执行（`odoo shell`）

```
STEP0 bundle=1255 bytes=1204972
STEP0 remote @import family params = ['Roboto:300,300i,400,400i,700,700i']
STEP0 -> fonts to localize = ['Roboto']
STEP1 OK in 2.5s ; font fetches=55 retries=0
STEP2 attachment 796 checksum fe7420acc10516066e86ecb5c2aceb1274be3d98
STEP2 line -> ["'google-local-fonts': ('Roboto': 1317),"]
STEP2 count name like google-font%% : 55
STEP2 main font-css attachment : [(1317, 'Roboto (google-font)', 'text/css', 33156)]
LOCALIZE_RC=0        （无 Traceback）
```

- `signal_changes()` 生效的直接证据：日志出现
  `Caches invalidated, signaling through the database: ['assets']`；
  `orm_signaling_assets` 的 `max(id)` 由 **3 → 4**。
- 生产网络远快于本机（本机 82.9 s / 93.5 s / 396 s，生产 **2.5 s**，`retries=0`）⇒ §8 第 2 条那条
  「下载步骤天生脆、要挑空闲窗口」在生产上**这次没有兑现**，但加固仍不可省。

### 10.4 第 3 步 · 三条硬判据（全过）

| # | 判据 | 生产实测 |
|---|---|---|
| 1 | `google-font%` 计数 **> 0** | **54**（+ `%(google-font)%` = 1 主 CSS ⇒ 合计 55，口径见 §3.3） |
| 2 | `googleapis = 0` 且 ≥ 1 条 `/web/content/…` | `googleapis=0`、`gstatic=0`、`/web/content/` = **4** |
| 3 | 本地字体 CSS **HTTP 200** | `/web/content/1317/google-font-Roboto` → **HTTP 200** |

> 判据 3 若照 §7 第 3 步**原文**的 `cut -d/ -f3` 跑，会得到 **404**（假红）—— 该缺陷已在 §7 第 3 步就地记录并修正。

### 10.5 验收明细（原始实测）

| 项 | 值 |
|---|---|
| **生产自己的附件 id** | **1317** —— **绝不能沿用本地 2449 / 2512 / 2570**（本机每次重跑都变，这正是 §7 与 §3.3 反复警告的那点） |
| `user_values.scss` 实际值 | `'google-local-fonts': ('Roboto': 1317),`（附件 796，store_fname `fe/fe7420ac…`，871 B） |
| served bundle | `/web/assets/1/**9915b9e**/web.assets_frontend.min.css`，**1,205,132 B**（改前 `9cc45bd` / 1,204,980 B） |
| bundle 首行 | `4 @import url("/web/content/1317/google-font-Roboto")`（4 个 alias 各一条，浏览器去重；见 §8 第 5 条） |
| 主字体 CSS 全文 | 33156 B；`src: url(` **54** 条，**全部**为本地 `/web/content/…`，远程 gstatic **0** 条 |
| **全链路** | **54/54 woff2 全部 HTTP 200 / `type=font/woff2`，failed=0** |
| 首条 woff2 sha256 | `d8d0c88eea1036dc3e7322cd0a1a3eb6fc1dd86da24c7de690e70aac1bd62f05` |
| ↑ 与 §3.3 记录比对 | **逐字相同** ⇒ 换的只是**交付路径**，不是字体字节；排版度量不可能变 |
| 跨进程一致性 | 10/10 次取样都拿到同一个新 bundle URL；6/6 次 CSS 的 `googleapis=0` ⇒ §4 那个「DB 改对了但 worker 继续发旧 bundle」的坑**未复现** |
| **未重启** | `StartedAt=2026-09-28T02:46:24Z RestartCount=0`，执行**前后完全相同** |
| 回归 | `/` 200、`/contactus` 200、`/alumni` 200、`/login` 200；登录（`backoffice@local`，uid=12）后 `/my/home` **200**（48355 B，无登录表单） |
| `/alumni` 修复仍在 | `href="/login?redirect=%2Falumni"` = **1**；`href="…/web/login?redirect…"` = **0**；原始串 `/web/login?redirect` = **0** |
| 反污染核对 | `batch2.py` `ac4319c5…`、`edu_portal_templates.xml` `0308f547…` —— 执行**前后四次取样全同**（宿主 + 容器），且与本地工作副本一致；mtime 仍 `2026-09-24` |
| 活体注册表门禁 | `python3 scripts/check_live_registry.py` → **PASS**，91/91 LIVE，**0 DARK**，RC=0 |
| 公网佐证 | `https://edu.example.org/` 200，同一 bundle `9915b9e`，`googleapis=0` / `gstatic=0`，4 条本地 `@import` |

### 10.6 回滚：**未使用，但可用**

执行书 §7 第 4 步的回滚脚本逐字可用（其「先回滚再应用」的端到端实测见 §6.2）；兜底为
**`/root/pre_font_20260928.gz`**（4,764,066 B；另需还原 filestore 副本）。
**本次没有触发回滚**，终态 = 已本地化。

### 10.7 §8 的三条残留：上线后**依然存在**（如实保留）

1. 每页 `<head>` 里仍有 `<link rel="preconnect" href="https://fonts.gstatic.com/" crossorigin>`
   （生产实测首页命中 **1**）—— **非阻塞**外链，失败即静默；A / B 方案**都不会**去掉它。
2. 编辑器专用 `website.website_builder_assets.min.css` 里仍有 **8 条** Google `@import` —— 只影响进网站编辑器的人。
3. 度量口径仍是 **`DOMContentLoaded`**，**不是** LCP / 首屏绘制 —— 阻塞机制已证实，视觉完整时间**没有**测。

### 10.8 两条运维事实（下次直接对生产跑之前先读）

- **生产 admin 口令不是本地默认值**：实测 `admin` / `demo123` →
  `POST /web/session/authenticate` 返回 HTTP 200 但 **`uid=None` / Access Denied**。
  ⇒ **`scripts/check_odoo_trace.py` 不能直接对生产跑**（其 `CRED_DEFAULTS['ADMIN']` 是本地值），
  且该门禁**必然报 `website.menu 62` 的 `/web/login`**。本次对 `/alumni` 的回归以**直接 curl 取证**替代
  （见 §10.5 那一行）；若要跑生产，须先用 `TRACE_ADMIN_PASSWORD` 等环境变量喂入真实凭据。
- **既有项照实记录、未修改**：`website.menu 62`（`url=/web/login`，`name=登录`）**仍然存在**，
  全库仅此 1 条指向 `/web/login`，它正是 `/alumni` 上那 2 个 `href="/web/login"` 的来源。
  这属**另一条独立议题**，本次**不动**。

---

## 11. 本文件未做的事（越界声明）

- **已执行生产步骤**：§7 已于 2026-09-28 在生产 `prod-host` 上按序执行完毕，命令原文、原始输出与
  逐项验收见 §10；其中 3 处会导致执行失败的写法已就地修正并回写（§3.3 / §7 第 0 步 / §7 第 3 步）。
- **没有做 B 方案**：§8.1 是源码级调研，**未执行、未验证效果**。
- **没有改任何仓内源码**：本次修复**零代码改动**，全部落在数据库行
  （`ir_attachment` / `ir_asset` 的自定义行）与 `orm_signaling_assets` 序号上。
